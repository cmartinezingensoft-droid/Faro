@echo off
setlocal

set MCP_DIR=C:\IA\Faro\MCP
set PUERTO=8765

echo ==========================================================
echo  Probador MCP Faro - reinicio en modo ESCRITURA
echo ==========================================================
echo.
echo Buscando si ya hay un probador escuchando en el puerto %PUERTO%...

set ENCONTRADO=0

REM Se usa PowerShell (Get-NetTCPConnection) porque su resultado no depende
REM del idioma de Windows. El metodo anterior con "netstat + findstr
REM LISTENING" nunca encontraba nada en un Windows en espanol, porque ahi
REM netstat pone "ESCUCHANDO" en vez de "LISTENING": el proceso viejo nunca
REM se mataba y se quedaba sirviendo la version anterior del probador aunque
REM se sustituyera el .py y se volviera a lanzar este .bat.
for /f "delims=" %%P in ('powershell -NoProfile -Command "try { (Get-NetTCPConnection -LocalPort %PUERTO% -State Listen -ErrorAction Stop).OwningProcess } catch { }" 2^>nul') do (
    if not "%%P"=="" (
        echo   Parando proceso anterior (PID %%P^)...
        taskkill /PID %%P /F >nul 2>&1
        set ENCONTRADO=1
    )
)

if "%ENCONTRADO%"=="0" (
    REM Respaldo por si PowerShell o Get-NetTCPConnection no estan
    REM disponibles en esta maquina. Se comprueban los dos textos posibles
    REM ("LISTENING" en ingles, "ESCUCHANDO" en espanol) para no repetir el
    REM mismo fallo.
    for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PUERTO% " ^| findstr /i "LISTENING ESCUCHANDO"') do (
        echo   Parando proceso anterior (PID %%P^)...
        taskkill /PID %%P /F >nul 2>&1
        set ENCONTRADO=1
    )
)

if "%ENCONTRADO%"=="0" (
    echo   No habia ninguna instancia previa escuchando en el puerto %PUERTO%.
) else (
    REM Pequena pausa para que Windows libere el puerto antes de reabrirlo.
    timeout /t 1 /nobreak >nul
)

echo.
echo Arrancando el probador MCP en modo ESCRITURA (FARO_MCP_ACCESS_LEVEL=write).
echo IMPORTANTE: en este modo las herramientas de escritura (grabar, borrar...^)
echo modifican de verdad tu base de datos Faro real. Revisa bien los datos
echo antes de pulsar "Ejecutar" en la pagina.
echo.

set FARO_MCP_ACCESS_LEVEL=write
cd /d "%MCP_DIR%"
"%MCP_DIR%\.venv\Scripts\python.exe" "%MCP_DIR%\scripts\mcp_tester_web.py"

echo.
echo El probador se ha parado (Ctrl+C o cierre de ventana).
pause
endlocal
