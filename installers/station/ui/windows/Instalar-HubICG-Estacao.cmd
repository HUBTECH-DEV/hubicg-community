@echo off
rem Ponto de entrada de clique duplo do instalador da estacao HubICG (interface W1).
rem Abre o assistente grafico no Windows PowerShell 5.1, que ja vem no sistema.
rem ExecutionPolicy Bypass vale so para este processo: nao muda a politica da maquina.
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File "%~dp0HubICG-Station-UI.ps1" %*
