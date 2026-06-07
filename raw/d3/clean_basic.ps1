# D3 基础验收脚本 (PowerShell 版)
# 等效于 clean_basic.py

$ErrorActionPreference = "Stop"

$root    = $PSScriptRoot
$inFile  = Join-Path $root "raw\d3\chat_sessions_dirty.csv"
$outFile = Join-Path $root "chat_sessions_clean.csv"

# ---------- 时间规整 ----------
$timeFmts = @(
    "yyyy/M/d H:m",
    "yyyy/M/d H:m:s",
    "yyyy-MM-ddTHH:mm:ss",
    "yyyy-MM-ddTHH:mm:sszzz",
    "yyyy-MM-ddTHH:mm",
    "yyyy-MM-dd HH:mm:ss",
    "yyyy-MM-dd HH:mm",
    "yyyy年M月d日 H:m:s",
    "yyyy年M月d日 H:m"
)

function Parse-Time($s, [ref]$invalid) {
    $invalid.Value = $true
    if ([string]::IsNullOrWhiteSpace($s)) { return $null }
    $s = $s.Trim()
    foreach ($f in $timeFmts) {
        try {
            $invalid.Value = $false
            return ([DateTime]::ParseExact($s, $f, $null)).ToString("yyyy-MM-dd HH:mm:ss")
        } catch {}
    }
    return $s
}

# ---------- 文本清洗 ----------
function Clean-Text([string]$s) {
    if ([string]::IsNullOrEmpty($s)) { return "" }
    $s = $s -replace '<[^>]+>', ''
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
    # 脱敏（在口水词处理前）
    $s = $s -replace '1[3-9]\d{9}', '[PHONE]'
    $s = $s -replace '[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}', '[EMAIL]'
    $s = $s.Trim()
    $s = $s -replace '^(嗯+|呃+|啊+|哦+|那个+|就是+)+', ''
    $s = $s -replace '^(嗯+|呃+|啊+|哦+|那个+|就是+)[… ]*', ''
    $s = $s -replace '(然后){2,}', '然后'
    $s = $s -replace '(那个){2,}', '那个'
    $s = $s -replace '啊啊啊+', ''
    $s = $s -replace '啊$', ''
    return $s.Trim()
}

# ---------- 读入 ----------
$rows = Import-Csv $inFile
Write-Host "input: $($rows.Count) rows"

# 1) 去重
$seen = @{}
$deduped = New-Object System.Collections.Generic.List[object]
$dupDropped = 0
foreach ($r in $rows) {
    $key = "{0}|{1}|{2}|{3}" -f $r.session_id, $r.user_id, $r.role, $r.message
    if ($seen.ContainsKey($key)) {
        $dupDropped++
        continue
    }
    $seen[$key] = $true
    $deduped.Add($r)
}
Write-Host "dedup: $dupDropped duplicate row(s) dropped, $($deduped.Count) kept"

# 2) 清洗 + 标记
$output = New-Object System.Collections.Generic.List[object]
foreach ($r in $deduped) {
    $flags = New-Object System.Collections.Generic.List[string]
    $inv = $false
    $iso = Parse-Time $r.created_at ([ref]$inv)
    $r.created_at = if ($iso) { $iso } else { "" }
    if ($inv) { $flags.Add("time_invalid") }
    if ([string]::IsNullOrWhiteSpace($r.user_id)) { $flags.Add("missing_user_id") }
    $orig = if ($r.message) { $r.message } else { "" }
    if ([string]::IsNullOrWhiteSpace($orig)) { $flags.Add("empty_message") }
    $cleaned = Clean-Text $orig
    if ($cleaned -match '\[PHONE\]') { $flags.Add("phone_masked") }
    if ($cleaned -match '\[EMAIL\]') { $flags.Add("email_masked") }
    $r.message = $cleaned
    $r | Add-Member -NotePropertyName flags -NotePropertyValue ($flags -join ",") -Force
    $output.Add($r)
}

# 3) 排序
$sorted = $output | Sort-Object @{Expression={$_.session_id}; Ascending=$true},
                               @{Expression={$_.created_at}; Ascending=$true}

# 4) 写文件
$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine("session_id,user_id,role,message,created_at,flags")
foreach ($r in $sorted) {
    $msg = $r.message -replace '"', '""'
    $line = '"{0}","{1}","{2}","{3}","{4}","{5}"' -f $r.session_id, $r.user_id, $r.role, $msg, $r.created_at, $r.flags
    [void]$sb.AppendLine($line)
}
[System.IO.File]::WriteAllText($outFile, $sb.ToString(), [System.Text.Encoding]::UTF8)

# 统计
$flagCounts = @{}
foreach ($r in $sorted) {
    foreach ($f in ($r.flags -split ",")) {
        if ($f) {
            $flagCounts[$f] = $flagCounts[$f] + 1
        }
    }
}
Write-Host "wrote $($sorted.Count) rows -> $outFile"
Write-Host "flag counts: $($flagCounts | ConvertTo-Json -Compress)"
