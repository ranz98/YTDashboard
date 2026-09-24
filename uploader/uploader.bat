@echo off

echo Opening YouTube Studio upload page...

start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" ^
    --profile-directory="Default" ^
    "https://studio.youtube.com/channel/UC4laQaWkDDNJt8x_2O935Ng/content?d=ud"

echo.
echo Waiting 10 seconds for YouTube Studio to start loading...
timeout /t 10 /nobreak >nul

echo.
echo Running Python script to choose a video and click Publish...

python -u "C:\Users\Administrator\Pictures\uploader\trainer.py" --next-clicks 4 %*


echo.
echo Done.

