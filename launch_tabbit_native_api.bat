@echo off
chcp 65001 >nul
echo 启动 Tabbit（注入原生 Chat API 桥，不改官方 UI）
start "" "E:\Users\Stone\AppData\Local\Tabbit Browser\Application\Tabbit Browser.exe" --load-extension="C:\Users\Stone\AppData\Local\Tabbit Browser\BYOK Extension"
echo.
echo 1. 打开官方 AI / Chat 侧栏
echo 2. 右下角点金色「API」按钮
echo 3. 勾选启用并填写 OpenAI/Anthropic
echo 4. 照常在官方输入框发消息
