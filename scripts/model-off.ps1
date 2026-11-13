# Unloads the model to free the GPU (for gaming etc.). Containers keep running;
# the chat UI stays up but replies fail until model-on.ps1 is run.

Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -match 'start-llama\.ps1' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Get-Process llama-server -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

if (Get-Process llama-server -ErrorAction SilentlyContinue) {
    Write-Output "Model server is still running."
    exit 1
}
$vram = (nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits) -join ''
Write-Output "Model unloaded. GPU memory in use now: $vram MiB."
