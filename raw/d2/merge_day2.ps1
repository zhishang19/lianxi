# D2 合并与去噪脚本 (PowerShell 版)
# 用于本机没有 Python 的环境，效果与 merge_day2.py 一致

$ErrorActionPreference = "Stop"

$root   = $PSScriptRoot
$rawDir = Join-Path $root "raw\d2"
$userPath = Join-Path $rawDir "user_behavior.json"
$toolPath = Join-Path $rawDir "tool_result.json"
$outPath  = Join-Path $root "merged.jsonl"

# ---------- 文本清洗 ----------
function Clean-Text([string]$s) {
    if ([string]::IsNullOrEmpty($s)) { return "" }
    # 1) 先清装饰符、HTML、emoji、全/半角空格
    $s = $s -replace '<!--.*?-->', ''
    $s = $s -replace '@{2,}', ''
    $s = $s -replace '!{2,}', '!'
    $s = $s -replace '！{2,}', '！'
    $s = $s -replace '\.{3,}', '…'
    $s = $s -replace '…{2,}', '…'
    $s = $s -replace '\*{2,}([^*]+?)\*{2,}', '$1'
    $s = $s -replace '[😅🙏😊😄🤣😂🤔😢😡🤮🤒🤕]', ''
    $s = $s -replace '　+', ' '
    $s = $s -replace ' {2,}', ' '
    $s = $s.Trim()
    # 2) 再清口水词（此时句首已是干净字符）
    $s = $s -replace '^(嗯+|呃+|啊+|哦+|那个+|就是+)+', ''
    $s = $s -replace '^(嗯+|呃+|啊+|哦+|那个+|就是+)[… ]*', ''
    $s = $s -replace '(然后){2,}', '然后'
    $s = $s -replace '(那个){2,}', '那个'
    $s = $s -replace '啊$', ''
    return $s.Trim()
}

# ---------- 时间解析 ----------
function Parse-Time($raw, [ref]$invalid) {
    $invalid.Value = $true
    if ($null -eq $raw) { return $null }
    $s = ([string]$raw).Trim()
    if ([string]::IsNullOrEmpty($s)) { return $null }
    $invalid.Value = $false

    $patterns = @(
        @{ r='^\d{4}/\d{1,2}/\d{1,2} \d{1,2}:\d{2}(:\d{2})?$'; f='yyyy/M/d H:m' }
        @{ r='^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:?\d{2})?$'; f='s' }
        @{ r='^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$'; f='yyyy-MM-dd HH:mm:ss' }
        @{ r='^\d{4}年\d{1,2}月\d{1,2}日 \d{1,2}:\d{2}(:\d{2})?$'; f='yyyy年M月d日 H:m' }
    )
    foreach ($p in $patterns) {
        if ($s -match $p.r) {
            try {
                if ($p.f -eq 's') {
                    return ([DateTime]$s).ToString('yyyy-MM-ddTHH:mm:ss')
                } else {
                    return ([DateTime]::ParseExact($s, $p.f, $null)).ToString('yyyy-MM-ddTHH:mm:ss')
                }
            } catch {
                $invalid.Value = $true
                return $s
            }
        }
    }
    $invalid.Value = $true
    return $s
}

# ---------- 读取并规范化 ----------
$userRaw = Get-Content $userPath -Raw -Encoding UTF8 | ConvertFrom-Json
$toolRaw = Get-Content $toolPath -Raw -Encoding UTF8 | ConvertFrom-Json

$records = New-Object System.Collections.Generic.List[object]

foreach ($r in $userRaw) {
    $uid      = if ($r.uid)       { $r.uid }       elseif ($r.user_id) { $r.user_id } else { $null }
    $timeRaw  = if ($r.time)      { $r.time }      elseif ($r.timestamp) { $r.timestamp } else { $null }
    $content  = if ($r.content)   { $r.content }   elseif ($r.text) { $r.text } else { "" }
    $type     = if ($r.action)    { $r.action }    elseif ($r.type)  { $r.type } else { "chat" }
    $inv = $false
    $iso = Parse-Time $timeRaw ([ref]$inv)
    $records.Add([PSCustomObject]@{
        source        = "user_behavior"
        uid           = $uid
        time          = $iso
        time_invalid  = $inv
        type          = $type
        content       = Clean-Text $content
    })
}

foreach ($r in $toolRaw.results) {
    $inv = $false
    $iso = Parse-Time ($r.time) ([ref]$inv)
    $records.Add([PSCustomObject]@{
        source          = "tool_result"
        uid             = $r.uid
        time            = $iso
        time_invalid    = $inv
        type            = $r.tool
        content         = Clean-Text $r.output
        tool_status     = $r.status
        tool_latency_ms = $r.latency_ms
        trace_id        = $r.trace_id
    })
}

# ---------- 去重 ----------
# 1) 严格相同 key 集合（带 trace_id 优先），重复时给被保留的记录 dup_count++
$stage1 = New-Object System.Collections.Generic.List[object]
$keptIndex = @{}  # key -> index in stage1
foreach ($r in $records) {
    $key = if ($r.trace_id) { "trace:{0}" -f $r.trace_id }
           else { "uid|{0}|time|{1}|content|{2}" -f $r.uid, $r.time, $r.content }
    if ($keptIndex.ContainsKey($key)) {
        $idx = $keptIndex[$key]
        $stage1[$idx].dup_count = $stage1[$idx].dup_count + 1
        continue
    }
    if (-not ($r.PSObject.Properties.Name -contains 'dup_count')) {
        $r | Add-Member -NotePropertyName dup_count -NotePropertyValue 1
    } else {
        $r.dup_count = 1
    }
    $stage1.Add($r)
    $keptIndex[$key] = $stage1.Count - 1
}

# 2) 同一 uid + 同一 time 合并（uid 与 time 都不为空才合并）
$byUT = @{}
$stage2 = New-Object System.Collections.Generic.List[object]
foreach ($r in $stage1) {
    if ($r.uid -and $r.time) {
        $k = "{0}|{1}" -f $r.uid, $r.time
        if ($byUT.ContainsKey($k)) {
            $byUT[$k].dup_count += 1
            continue
        }
        if (-not ($r.PSObject.Properties.Name -contains 'dup_count')) {
        $r | Add-Member -NotePropertyName dup_count -NotePropertyValue 1
    }
    # 不再重置 dup_count
    $byUT[$k] = $r
    $stage2.Add($r)
} else {
    if (-not ($r.PSObject.Properties.Name -contains 'dup_count')) {
        $r | Add-Member -NotePropertyName dup_count -NotePropertyValue 1
    }
    $stage2.Add($r)
}
}

# 3) 同一 uid 内文本相似度 ≥ 0.9 合并
function Get-Ratio($a, $b) {
    if ([string]::IsNullOrEmpty($a) -or [string]::IsNullOrEmpty($b)) { return 0 }
    if ($a -eq $b) { return 1 }
    $la = $a.Length; $lb = $b.Length
    $len = [Math]::Max($la, $lb)
    $dist = 0
    # 简化：取短串和长串的公共子串比例
    $min = if ($la -le $lb) { $a } else { $b }
    $max = if ($la -le $lb) { $b } else { $a }
    if ($max.Contains($min)) { return [double]$min.Length / $len }
    $common = 0
    for ($i = 0; $i -lt $min.Length; $i++) {
        if ($max.IndexOf($min.Substring($i,1)) -ge 0) { $common++ }
    }
    return [double]$common / $len
}

$final = New-Object System.Collections.Generic.List[object]
foreach ($r in $stage2) {
    $merged = $false
    foreach ($f in $final) {
        if ($r.uid -and $r.uid -eq $f.uid -and $r.content -and $f.content) {
            $ratio = Get-Ratio $r.content $f.content
            if ($ratio -ge 0.9) {
                $f.dup_count += 1
                $merged = $true
                break
            }
        }
    }
    if (-not $merged) { $final.Add($r) }
}

# ---------- 排序：无效时间排最后 ----------
$sorted = $final | Sort-Object @{Expression={$_.time_invalid}; Ascending=$true},
                                @{Expression={$_.time}; Ascending=$true},
                                @{Expression={$_.uid}; Ascending=$true}

# ---------- 写文件 ----------
$lines = $sorted | ForEach-Object { $_ | ConvertTo-Json -Compress -Depth 5 }
[System.IO.File]::WriteAllLines($outPath, $lines, [System.Text.Encoding]::UTF8)

Write-Host "wrote $($sorted.Count) records -> $outPath"
foreach ($r in $sorted) {
    $flag = if ($r.time_invalid) { " [invalid_time]" } else { "" }
    $uidStr = if ($r.uid) { $r.uid } else { "-" }
    $timeStr = if ($r.time) { $r.time } else { "null" }
    Write-Host ("  - {0,-13} {1,-5} {2,-19}{3} type={4} content={5}" -f $r.source, $uidStr, $timeStr, $flag, $r.type, ($r.content.Substring(0,[Math]::Min(60,$r.content.Length))))
}
