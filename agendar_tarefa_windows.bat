@echo off
chcp 65001 > nul
echo ======================================================================
echo   SmartDiet - Configurador de Agendamento Diario (Windows Task Scheduler)
echo ======================================================================
echo.
echo Este script agenda a execucao automatica do robo 1.py todos os dias as 04:00 AM.
echo.

set PYTHON_PATH="c:\Users\andre.suhai\AppData\Local\Programs\Python\Python312\python.exe"
set SCRIPT_PATH="c:\Users\andre.suhai\Documents\Insper APP\1.py"
set TASK_NAME="SmartDiet_Precos_Diario"

echo Criando/Atualizando a tarefa agendada: %TASK_NAME% ...
schtasks /create /tn %TASK_NAME% /tr "%PYTHON_PATH% %SCRIPT_PATH%" /sc daily /st 04:00 /f

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Tarefa agendada com sucesso!
    echo O robo de precos ira rodar todos os dias de madrugada as 04:00.
    echo.
    echo Para executar agora manualmente para testar o agendamento:
    echo   schtasks /run /tn %TASK_NAME%
) else (
    echo.
    echo [!] Erro ao criar a tarefa agendada. Tente executar este arquivo como Administrador.
)

echo.
pause
