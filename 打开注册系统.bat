@echo off
chcp 936 >nul
title BNU AI Lab 注册系统 - SSH 隧道
color 0B

echo.
echo  ======================================================
echo     BNU AI Lab   ·   26 级成员注册
echo  ======================================================
echo.
echo     正在连接  47.118.28.10 ...
echo.
echo     隧道建立后约 5 秒，浏览器会自动打开
echo     如果需要手动访问： http://127.0.0.1:8082/register
echo.
echo     关闭此窗口 = 断开隧道 = 页面立即失效
echo  ======================================================
echo.

start "" /b cmd /c "ping -n 6 127.0.0.1 >nul && start http://127.0.0.1:8082/register"

ssh -N -L 8082:127.0.0.1:8081 root@47.118.28.10

echo.
echo  隧道已断开。按任意键关闭。
pause >nul
