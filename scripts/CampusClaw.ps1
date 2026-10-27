# Windows PowerShell 5.1 compatible. Local configuration is parsed as data, never executed.
[CmdletBinding()]
param([ValidateSet('Start','Stop')][string]$Action='Start', [switch]$NoBrowser)
$ErrorActionPreference='Stop'
$script:Root=[IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$script:LogDir=Join-Path $Root 'logs'
$script:Runtime=Join-Path $Root 'temp/launcher'
[IO.Directory]::CreateDirectory($LogDir) | Out-Null
[IO.Directory]::CreateDirectory($Runtime) | Out-Null
$script:Log=Join-Path $LogDir 'launcher.log'
$script:StateFile=Join-Path $Runtime 'processes.json'
$script:State=@{Backend=$null;Nginx=$null}
$script:StateLoaded=$false
$script:NewProcesses=New-Object System.Collections.ArrayList
$script:Keys=@('CAMPUSCLAW_INITIAL_TEACHER_PASSWORD','CAMPUSCLAW_MCP_MAX_ROUNDS','CAMPUSCLAW_MCP_MAX_CALLS','CAMPUSCLAW_MCP_ALLOWED_URLS','CAMPUSCLAW_TOKEN_SECRET','CAMPUSCLAW_ASSISTANT_DB','CHAT_BASE_URL','CHAT_API_KEY','CHAT_MODEL','EMBEDDING_BASE_URL','EMBEDDING_API_KEY','EMBEDDING_MODEL','EMBEDDING_DIM','AI_GATEWAY_BASE_URL','AI_GATEWAY_API_KEY','AI_CHAT_MODEL','AI_EMBEDDING_MODEL','AI_GATEWAY_TIMEOUT_SECONDS','AI_STREAM_TOTAL_SECONDS','CAMPUSCLAW_PYTHON','CAMPUSCLAW_NGINX')

function Write-Status([string]$Message) {
    $line='['+(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')+'] '+$Message
    Write-Host $Message
    Add-Content -LiteralPath $script:Log -Value $line -Encoding UTF8
}
function Hash-Text([string]$Text) {
    $sha=[Security.Cryptography.SHA256]::Create()
    try {return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace('-','').ToLowerInvariant()}
    finally {$sha.Dispose()}
}
function Load-State {
    if (Test-Path -LiteralPath $StateFile) {
        try {
            $saved=Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($saved.Root -ne $Root) {throw 'different project'}
            $script:State=@{Backend=$saved.Backend;Nginx=$saved.Nginx}
        } catch {throw '进程管理记录损坏或属于其他目录。为避免误停进程，已停止操作。请查看“一键启动说明.md”。'}
    }
}
function Save-State {
    @{Root=$Root;Backend=$State.Backend;Nginx=$State.Nginx} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath ($StateFile+'.tmp') -Encoding UTF8
    Move-Item -LiteralPath ($StateFile+'.tmp') -Destination $StateFile -Force
}
function Process-Info([int]$ProcessId) {
    return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}
function Process-Record($Info,[string]$Kind,[bool]$Managed,[string]$Fingerprint) {
    return [pscustomobject]@{Id=[int]$Info.ProcessId;Created=$Info.CreationDate.ToUniversalTime().ToString('o');Executable=$Info.ExecutablePath;Command=$Info.CommandLine;Kind=$Kind;Managed=$Managed;Fingerprint=$Fingerprint}
}
function Same-Process($Record) {
    if ($null -eq $Record) {return $false}
    $info=Process-Info $Record.Id
    if (!$info -or !$info.ExecutablePath -or !$info.CommandLine) {return $false}
    return ($info.CreationDate.ToUniversalTime().ToString('o') -eq $Record.Created -and $info.ExecutablePath -eq $Record.Executable -and $info.CommandLine -eq $Record.Command)
}
function Is-ProjectProcess($Info,[string]$Kind,[string]$Executable) {
    if (!$Info -or !$Info.CommandLine -or $Info.ExecutablePath -ne $Executable) {return $false}
    $command=$Info.CommandLine.Replace('\','/').ToLowerInvariant()
    $project=$Root.Replace('\','/').ToLowerInvariant()
    if ($Kind -eq 'Backend') {return $command.Contains($project+'/backend/server.py')}
    return ($command.Contains($project+'/') -and $command -match '(?i)(^|\s)-p\s' -and $command -match '(?i)(^|\s)-c\s+"?(?:[^"\s]*/)?nginx/nginx\.conf"?(\s|$)')
}
function Listeners([int]$Port) {
    return @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
}
function Port-Error([int]$Port) {
    $details=@(Listeners $Port | ForEach-Object {$p=Process-Info $_; if ($p) {"PID $($p.ProcessId) ($($p.Name))"} else {"PID $_"}}) -join '、'
    throw "端口 $Port 被其他程序或无法确认归属的服务占用：$details。未关闭该程序。请先退出占用程序，或查看一键启动说明。"
}
function Read-LocalConfig {
    $path=Join-Path $Root '.env'
    if (!(Test-Path -LiteralPath $path)) {
        Copy-Item -LiteralPath (Join-Path $Root '.env.example') -Destination $path
        Write-Status '已创建本地 .env 配置文件（已由 Git 忽略）。'
    }
    $lineNumber=0
    $configLines=[IO.File]::ReadAllLines($path,[Text.Encoding]::UTF8)
    $secretIndex=-1
    foreach ($line in $configLines) {
        $lineNumber++
        $text=$line.Trim()
        if (!$text -or $text.StartsWith('#')) {continue}
        if ($text -notmatch '^([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {throw ".env 第 $lineNumber 行格式错误，应为 KEY=value。配置内容未写入日志。"}
        $key=$matches[1];$value=$matches[2].Trim()
        if ($key -eq 'CAMPUSCLAW_TOKEN_SECRET') {$secretIndex=$lineNumber-1}
        if ($Keys -notcontains $key) {throw ".env 第 $lineNumber 行包含不支持的配置项，请查看 .env.example。"}
        if ($value.StartsWith('"') -or $value.StartsWith("'")) {
            if ($value.Length -lt 2 -or $value[$value.Length-1] -ne $value[0]) {throw ".env 第 $lineNumber 行引号不匹配。"}
            $value=$value.Substring(1,$value.Length-2)
        }
        [Environment]::SetEnvironmentVariable($key,$value,'Process')
    }
    if ([string]::IsNullOrWhiteSpace($env:CAMPUSCLAW_TOKEN_SECRET)) {
        $bytes=New-Object byte[] 48
        $rng=[Security.Cryptography.RandomNumberGenerator]::Create()
        try {$rng.GetBytes($bytes)} finally {$rng.Dispose()}
        $env:CAMPUSCLAW_TOKEN_SECRET=[Convert]::ToBase64String($bytes)
        if ($secretIndex -ge 0) {
            $configLines[$secretIndex]='CAMPUSCLAW_TOKEN_SECRET='+$env:CAMPUSCLAW_TOKEN_SECRET
            [IO.File]::WriteAllLines($path,$configLines,(New-Object Text.UTF8Encoding($false)))
        } else {
            [IO.File]::AppendAllText($path,"`r`n# 自动生成的本地稳定签名密钥，请勿公开或提交。`r`nCAMPUSCLAW_TOKEN_SECRET=$($env:CAMPUSCLAW_TOKEN_SECRET)`r`n",(New-Object Text.UTF8Encoding($false)))
        }
        Write-Status '已生成并保存稳定签名密钥；后续启动将复用，不会在日志中显示。'
    }
    $effective=@($Keys | Where-Object {$_ -notin @('CAMPUSCLAW_PYTHON','CAMPUSCLAW_NGINX')} | ForEach-Object {$_+'='+[Environment]::GetEnvironmentVariable($_,'Process')}) -join "`n"
    $script:BackendHash=Hash-Text $effective
    $base=@($env:CHAT_BASE_URL,$env:EMBEDDING_BASE_URL,$env:AI_GATEWAY_BASE_URL | Where-Object {$_}) | Select-Object -First 1
    $key=@($env:CHAT_API_KEY,$env:EMBEDDING_API_KEY,$env:AI_GATEWAY_API_KEY | Where-Object {$_}) | Select-Object -First 1
    if (!$base -or !$key -or $base -match '[<>]' -or $key -match '[<>]') {
        Write-Status '提示：AI 模型尚未配置，网站可以正常使用，AI 聊天暂不可用。请在 .env 填写 CHAT_BASE_URL、CHAT_API_KEY、CHAT_MODEL 后重新双击启动。'
    }
    if ($env:CAMPUSCLAW_ASSISTANT_DB -and ![IO.Path]::IsPathRooted($env:CAMPUSCLAW_ASSISTANT_DB)) {
        $env:CAMPUSCLAW_ASSISTANT_DB=[IO.Path]::GetFullPath((Join-Path $Root $env:CAMPUSCLAW_ASSISTANT_DB))
    }
}
function Find-Python {
    $candidates=@()
    if ($env:CAMPUSCLAW_PYTHON) {$candidates=@($env:CAMPUSCLAW_PYTHON)}
    else {
        $candidates+=Join-Path $env:LOCALAPPDATA 'Programs/Python/Python312/python.exe'
        $cmd=Get-Command python.exe -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notlike '*WindowsApps*') {$candidates+=$cmd.Source}
        $base=Join-Path $env:LOCALAPPDATA 'Programs/Python'
        if (Test-Path -LiteralPath $base) {$candidates+=@(Get-ChildItem -LiteralPath $base -Directory | Sort-Object Name -Descending | ForEach-Object {Join-Path $_.FullName 'python.exe'})}
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (!(Test-Path -LiteralPath $candidate -PathType Leaf)) {continue}
        try {
            $probe=& $candidate -c 'import sys,sqlite3; print(sys.executable); sys.exit(sys.version_info < (3,10))' 2>$null
            if ($LASTEXITCODE -eq 0 -and $probe) {return [IO.Path]::GetFullPath($candidate)}
        } catch {}
    }
    throw '找不到可用的 Python 3.10+（需包含 sqlite3）。请在项目 .env 设置 CAMPUSCLAW_PYTHON=python.exe 的完整路径，不能使用 WindowsApps 占位程序。'
}
function Find-Nginx {
    $candidates=@()
    if ($env:CAMPUSCLAW_NGINX) {$candidates=@($env:CAMPUSCLAW_NGINX)}
    else {
        $cmd=Get-Command nginx.exe -ErrorAction SilentlyContinue
        if ($cmd) {$candidates+=$cmd.Source}
        $candidates+=Join-Path $Root 'nginx/nginx.exe'
        foreach ($parent in @('D:/sp','C:/nginx','D:/nginx')) {
            if (Test-Path -LiteralPath $parent) {
                $candidates+=Join-Path $parent 'nginx.exe'
                foreach ($dir in @(Get-ChildItem -LiteralPath $parent -Directory -Filter 'nginx*')) {
                    $candidates+=Join-Path $dir.FullName 'nginx.exe'
                    $candidates+=Join-Path $dir.FullName ($dir.Name+'/nginx.exe')
                }
            }
        }
    }
    foreach ($candidate in $candidates) {if (Test-Path -LiteralPath $candidate -PathType Leaf) {return [IO.Path]::GetFullPath($candidate)}}
    throw '找不到 Nginx。请在项目 .env 设置 CAMPUSCLAW_NGINX=nginx.exe 的完整路径。例如 D:/sp/nginx-1.31.6/nginx-1.31.6/nginx.exe。'
}
function Http-Json([string]$Url) {
    return Invoke-RestMethod -Uri $Url -TimeoutSec 3 -Proxy $null -ErrorAction Stop
}
function Backend-Healthy([int]$Port) {
    try {
        $health=Http-Json "http://127.0.0.1:$Port/health"
        $version=Http-Json "http://127.0.0.1:$Port/app-version"
        return ($health.success -and $health.service -eq 'CampusClaw backend' -and $health.status -eq 'ok' -and $version.version -eq 'CampusClaw-bearer-token-v3')
    } catch {return $false}
}
function Web-Healthy {
    if (!(Backend-Healthy 8080)) {return $false}
    try {
        $page=Invoke-WebRequest -Uri 'http://127.0.0.1:8080/' -UseBasicParsing -TimeoutSec 3 -Proxy $null
        $expected=[IO.File]::ReadAllText((Join-Path $Root 'frontend/index.html'),[Text.Encoding]::UTF8)
        # Nginx may omit an explicit charset. Decode RawContentStream as UTF-8
        # before comparing the actual page to this checkout's file.
        $actual=[Text.Encoding]::UTF8.GetString($page.RawContentStream.ToArray())
        return ($page.StatusCode -eq 200 -and $actual -eq $expected)
    } catch {return $false}
}
function Wait-Health([string]$Kind,[int]$Seconds=60) {
    $deadline=(Get-Date).AddSeconds($Seconds)
    do {
        if ($Kind -eq 'Backend') {$ok=Backend-Healthy 5000} else {$ok=Web-Healthy}
        if ($ok) {return}
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "$Kind 健康检查超时。请查看 logs/backend.stderr.log、logs/backend.stdout.log 和 logs/error.log；启动器没有打开浏览器。"
}
function Stop-Backend($Record) {
    if ($Record -and $Record.Managed -and (Same-Process $Record)) {
        $info=Process-Info $Record.Id
        if (!(Is-ProjectProcess $info 'Backend' $Record.Executable)) {throw '后端归属校验失败，未停止任何进程。'}
        Stop-Process -Id $Record.Id -ErrorAction Stop
        Write-Status "已停止本启动器管理的 Python 后端（PID $($Record.Id)）。"
    }
}
function Invoke-Nginx([string]$Exe,[string[]]$Extra) {
    $prefix=$Root.Replace('\','/')+'/'
    $previous=$ErrorActionPreference
    try {
        # Windows PowerShell treats native stderr as ErrorRecord, even for a
        # successful nginx -t. Check the native exit code rather than stderr.
        $ErrorActionPreference='Continue'
        $out=& $Exe '-p' $prefix '-c' 'nginx/nginx.conf' @Extra 2>&1
        $code=$LASTEXITCODE
    } finally {$ErrorActionPreference=$previous}
    # Never log configuration values; Nginx diagnostics refer only to paths/directives.
    foreach ($line in $out) {Add-Content -LiteralPath (Join-Path $LogDir 'nginx-launcher.log') -Value ([string]$line) -Encoding UTF8}
    if ($code -ne 0) {throw 'Nginx 配置检查或控制失败。请查看 logs/nginx-launcher.log 和 logs/error.log。'}
}
function Nginx-Master([string]$Exe) {
    $pidFile=Join-Path $Root 'logs/nginx.pid'
    if (!(Test-Path -LiteralPath $pidFile)) {return $null}
    $number=0
    if (![int]::TryParse(([IO.File]::ReadAllText($pidFile)).Trim(),[ref]$number)) {return $null}
    $info=Process-Info $number
    if (Is-ProjectProcess $info 'Nginx' $Exe) {return $info}
    return $null
}
function Port-BelongsToNginx($Master) {
    $owners=@(Listeners 8080)
    if (!$Master -or !$owners.Count) {return $false}
    foreach ($owner in $owners) {
        $info=Process-Info $owner
        if (!$info -or $info.ExecutablePath -ne $Master.ExecutablePath) {return $false}
        if ($info.ProcessId -ne $Master.ProcessId -and $info.ParentProcessId -ne $Master.ProcessId) {return $false}
    }
    return $true
}
function Stop-Nginx($Record) {
    if ($Record -and $Record.Managed -and (Same-Process $Record)) {
        $master=Nginx-Master $Record.Executable
        if (!$master -or $master.ProcessId -ne $Record.Id) {throw 'Nginx 主进程或 PID 文件归属不一致，未发送停止命令。'}
        Invoke-Nginx $Record.Executable @('-s','quit')
        $deadline=(Get-Date).AddSeconds(15)
        while ((Same-Process $Record) -and (Get-Date) -lt $deadline) {Start-Sleep -Milliseconds 250}
        if (Same-Process $Record) {throw 'Nginx 正在等待连接退出，暂未完成停止；未强杀任何进程。稍后再双击停止。'}
        Write-Status '已正常停止本启动器管理的 Nginx。'
    }
}
function Start-Detached([string]$Python,[string]$Name,[string[]]$Command) {
    $helper=Join-Path $Root 'scripts/launch_process.py'
    $output=Join-Path $LogDir ($Name+'.stdout.log')
    $errors=Join-Path $LogDir ($Name+'.stderr.log')
    $number=& $Python $helper '--cwd' $Root '--stdout' $output '--stderr' $errors @Command
    if ($LASTEXITCODE -ne 0 -or !$number) {throw "$Name 服务启动失败，请查看 logs 目录日志。"}
    return [int]$number
}
function Start-Services {
    Read-LocalConfig
    $python=Find-Python
    $nginx=Find-Nginx
    Write-Status "Python：$python"
    Write-Status "Nginx：$nginx"
    # Validate everything possible before starting a service.
    Invoke-Nginx $nginx @('-t')
    $owners=@(Listeners 5000)
    if ($owners.Count) {
        if ($owners.Count -ne 1 -or !(Is-ProjectProcess (Process-Info $owners[0]) 'Backend' $python)) {Port-Error 5000}
    }
    $master=Nginx-Master $nginx
    if (@(Listeners 8080).Count -and !(Port-BelongsToNginx $master)) {Port-Error 8080}
    if ($owners.Count) {
        $info=Process-Info $owners[0]
        $managed=$State.Backend -and $State.Backend.Managed -and (Same-Process $State.Backend)
        if ($managed -and $State.Backend.Fingerprint -ne $BackendHash) {
            Write-Status '检测到本地后端配置变化，正在重新启动本启动器管理的后端以应用配置。'
            Stop-Backend $State.Backend
            $owners=@()
        } else {
            Wait-Health 'Backend' 10
            $State.Backend=Process-Record $info 'Backend' ([bool]$managed) $BackendHash
            if (!$managed) {Write-Status '复用手动启动的本项目后端：不会取得停止权限；若需应用新的 .env 配置，请先手动关闭原后端再启动。'}
            else {Write-Status '后端已健康运行，复用现有进程。'}
        }
    }
    if (!$owners.Count) {
        $env:PYTHONUNBUFFERED='1';$env:PYTHONIOENCODING='utf-8'
        $backendScript=Join-Path $Root 'backend/server.py'
        $processId=Start-Detached $python 'backend' @($python,'-u',$backendScript)
        $info=Process-Info $processId
        if (!$info) {throw 'Python 后端启动失败，请查看 logs/backend.stderr.log。'}
        $State.Backend=Process-Record $info 'Backend' $true $BackendHash
        [void]$NewProcesses.Add($State.Backend)
        Save-State
        Write-Status "正在启动后端（PID $processId），等待 HTTP 健康检查……"
        Wait-Health 'Backend'
        if (!(Same-Process $State.Backend) -or @((Listeners 5000) | Where-Object {$_ -ne $State.Backend.Id}).Count) {Port-Error 5000}
    }
    $nginxHash=Hash-Text ([IO.File]::ReadAllText((Join-Path $Root 'nginx/nginx.conf')))
    $master=Nginx-Master $nginx
    if ($master) {
        $managed=$State.Nginx -and $State.Nginx.Managed -and (Same-Process $State.Nginx)
        if (!$State.Nginx -or !(Same-Process $State.Nginx) -or $State.Nginx.Fingerprint -ne $nginxHash) {
            Write-Status 'Nginx 已运行，正在重新加载已检查的当前项目配置。'
            Invoke-Nginx $nginx @('-s','reload')
        } else {Write-Status 'Nginx 已运行且配置未变化，无需重复启动或重载。'}
        $State.Nginx=Process-Record $master 'Nginx' ([bool]$managed) $nginxHash
    } else {
        $prefix=$Root.Replace('\','/')+'/'
        $processId=Start-Detached $python 'nginx' @($nginx,'-p',$prefix,'-c','nginx/nginx.conf')
        $deadline=(Get-Date).AddSeconds(10)
        do {$master=Nginx-Master $nginx;if ($master) {break};Start-Sleep -Milliseconds 250} while ((Get-Date) -lt $deadline)
        if (!$master) {throw 'Nginx 启动失败，未找到可确认归属的主进程。请查看 logs/error.log。'}
        $State.Nginx=Process-Record $master 'Nginx' $true $nginxHash
        [void]$NewProcesses.Add($State.Nginx)
        Write-Status "正在启动 Nginx（PID $($master.ProcessId)），等待代理与首页健康检查……"
    }
    Save-State
    Wait-Health 'Nginx' 20
    # Reload swaps workers asynchronously. A listener PID can disappear between
    # TCP enumeration and CIM lookup; retry rather than misreport a conflict.
    $ownershipDeadline=(Get-Date).AddSeconds(10)
    $owned=$false
    do {
        $owned=Port-BelongsToNginx (Nginx-Master $nginx)
        if ($owned) {break}
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $ownershipDeadline)
    if (!$owned) {Port-Error 8080}
    Write-Status 'CampusClaw 启动成功：后端、Nginx 代理和当前项目首页均可访问。'
    Write-Status '网站：http://127.0.0.1:8080/；结束使用后请双击“停止CampusClaw.bat”。'
    if (!$NoBrowser) {
        try {
            # A GUI browser must not inherit the bat/PowerShell console pipes.
            $browserHelper=Join-Path $Root 'scripts/launch_process.py'
            $browserProcessId=Start-Detached $python 'browser' @($python,$browserHelper,'--open-browser')
            Write-Status '已请求默认浏览器打开 CampusClaw 网站。'
        }
        catch {Write-Status '网站已启动，但默认浏览器未能自动打开，请手动访问 http://127.0.0.1:8080/。'}
    }
}

$mutex=New-Object Threading.Mutex($false,('Local\CampusClaw-'+(Hash-Text $Root.ToLowerInvariant()).Substring(0,24)))
$locked=$false
try {
    try {$locked=$mutex.WaitOne(0)} catch [Threading.AbandonedMutexException] {$locked=$true}
    if (!$locked) {throw '另一个 CampusClaw 启动或停止操作正在进行，请等待其完成后再试。'}
    Set-Location -LiteralPath $Root
    Load-State
    $script:StateLoaded=$true
    Write-Status "开始操作：$Action；项目：$Root"
    if ($Action -eq 'Start') {Start-Services}
    else {
        Stop-Nginx $State.Nginx
        Stop-Backend $State.Backend
        foreach ($name in @('Backend','Nginx')) {
            if ($State[$name] -and !(Same-Process $State[$name])) {$State[$name]=$null}
            elseif ($State[$name] -and !$State[$name].Managed) {Write-Status "$name 为手动启动的进程，已保留，不会误关闭。"}
        }
        Save-State
        Write-Status '停止操作完成。数据库、账号、材料和本地配置均保留。'
    }
    exit 0
} catch {
    # Only roll back newly launched processes, never existing/manual services.
    if ($locked) {
        foreach ($record in @($NewProcesses | Sort-Object Kind -Descending)) {
            try {if ($record.Kind -eq 'Nginx') {Stop-Nginx $record} else {Stop-Backend $record}} catch {}
        }
        if ($StateLoaded) {try {Save-State} catch {}}
    }
    Write-Status ('启动/停止失败：'+$_.Exception.Message)
    Write-Status '排查说明：项目根目录“一键启动说明.md”；日志：logs/launcher.log。请勿直接结束所有 Python 或 Nginx 进程。'
    exit 1
} finally {
    if ($locked) {$mutex.ReleaseMutex()}
    $mutex.Dispose()
}
