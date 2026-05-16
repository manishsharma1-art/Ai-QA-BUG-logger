@echo off
REM Quick deployment script for bug fixes (Windows)

echo ==========================================
echo QA Bug Logger - Deploying Timeout Fixes
echo ==========================================

REM Configuration - UPDATE THESE
set PROJECT_ID=your-gcp-project-id
set REGION=asia-south1
set SERVICE_NAME=qa-bugbot
set IMAGE_NAME=gcr.io/%PROJECT_ID%/%SERVICE_NAME%

echo.
echo Step 1: Building Docker image...
docker build -t %SERVICE_NAME% .
if errorlevel 1 goto error

echo.
echo Step 2: Tagging image for GCR...
docker tag %SERVICE_NAME% %IMAGE_NAME%:latest
if errorlevel 1 goto error

echo.
echo Step 3: Pushing to Google Container Registry...
docker push %IMAGE_NAME%:latest
if errorlevel 1 goto error

echo.
echo Step 4: Deploying to Cloud Run...
gcloud run deploy %SERVICE_NAME% ^
  --image %IMAGE_NAME%:latest ^
  --platform managed ^
  --region %REGION% ^
  --memory 512Mi ^
  --cpu 1 ^
  --timeout 300 ^
  --max-instances 10
if errorlevel 1 goto error

echo.
echo ==========================================
echo ✅ Deployment complete!
echo ==========================================
echo.
echo Verify deployment:
echo   gcloud run services describe %SERVICE_NAME% --region %REGION%
echo.
echo Check logs:
echo   gcloud run services logs read %SERVICE_NAME% --region %REGION% --limit 50
echo.
goto end

:error
echo.
echo ❌ Deployment failed!
echo.
exit /b 1

:end
