param([string]$BaseUrl = "http://127.0.0.1:8000")

$ErrorActionPreference = "Stop"
$envFile = Join-Path $PSScriptRoot ".env"
$keyLine = Get-Content $envFile | Where-Object { $_ -match '^OFFICER_API_KEY=' } | Select-Object -First 1
if (-not $keyLine) { throw "OFFICER_API_KEY was not found in backend/.env" }
$officerKey = $keyLine.Substring("OFFICER_API_KEY=".Length).Trim().Trim('"').Trim("'")
$headers = @{ "X-API-Key" = $officerKey }

$complaints = @()
foreach ($description in @(
    "The general help desk is difficult to locate.",
    "Please review the service delay at the hospital help desk.",
    "The hospital service desk has not responded to my request."
)) {
    $payload = @{ description = $description; language = "en"; hospital_id = 1; channel = "assisted" } | ConvertTo-Json
    $created = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/complaints" -ContentType "application/json" -Headers $headers -Body $payload
    $due = [DateTimeOffset]::Parse($created.due_at)
    $slaHours = ($due - [DateTimeOffset]::UtcNow).TotalHours
    $complaints += [pscustomobject]@{ Id = $created.complaint_id; SlaHours = $slaHours; DueAt = $created.due_at }
}

# Put one complaint 3h before due, one 1h overdue, and one 3h overdue.
$shifts = @([math]::Max(0.1, $complaints[0].SlaHours - 3), $complaints[1].SlaHours + 1, $complaints[2].SlaHours + 3)
for ($i = 0; $i -lt $complaints.Count; $i++) {
    $hours = [math]::Round($shifts[$i], 2)
    Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/demo/backdate/$($complaints[$i].Id)?hours=$hours" -Headers $headers | Out-Null
}

Write-Host "Registered complaint IDs and backdate amounts:"
for ($i = 0; $i -lt $complaints.Count; $i++) {
    Write-Host ("{0}  shifted {1} hours" -f $complaints[$i].Id, [math]::Round($shifts[$i], 2))
}

Write-Host "Scheduler result:"
Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/followups/run" -Headers $headers | ConvertTo-Json -Depth 5
Write-Host "Follow-up groups:"
Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/followups" -Headers $headers | ConvertTo-Json -Depth 8
Write-Host "Outbox notifications:"
Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/notifications" -Headers $headers | ConvertTo-Json -Depth 8
