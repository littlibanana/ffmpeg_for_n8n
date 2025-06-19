import asyncio
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

# --- Application Settings ---
app = FastAPI(
    title="AAC to MP4 Converter with Fixed Image",
    description="An API to convert AAC to MP4 using a fixed 'logo.png' image.",
)

# Create a temporary directory to store uploaded and output files
TEMP_DIR = Path("temp_files")
TEMP_DIR.mkdir(exist_ok=True)

# Define the path to the fixed logo image
LOGO_PATH = Path("logo.png")


# --- FFmpeg Check ---
def check_ffmpeg_installed():
    """Checks if FFmpeg is installed and accessible in the system PATH."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "FFmpeg not found. Please install FFmpeg and ensure it's in the system's PATH."
        )


# Run check on startup
check_ffmpeg_installed()

# Check if logo.png exists on startup
if not LOGO_PATH.exists():
    raise RuntimeError("logo.png file not found in the working directory.")


# --- Cleanup Function ---
def cleanup_files(paths: list[Path]):
    """Deletes the specified temporary files."""
    for path in paths:
        if path and path.exists():
            path.unlink()


# --- API Endpoint ---
@app.post("/convert/", tags=["Conversion"])
async def convert_aac_to_mp4_with_logo(
    audio_file: UploadFile = File(..., description="The AAC audio file to convert."),
):
    """
    Converts an AAC file to an MP4 video using a fixed 'logo.png' image.
    The 'logo.png' will be used as the visual track for the entire duration of the audio.
    """
    job_id = str(uuid.uuid4())
    files_to_clean = []

    try:
        # --- Save Uploaded Audio File ---
        input_aac_path = TEMP_DIR / f"{job_id}_{audio_file.filename}"
        await _save_upload_file(audio_file, input_aac_path)
        files_to_clean.append(input_aac_path)

        output_mp4_path = TEMP_DIR / f"{job_id}_output.mp4"
        files_to_clean.append(output_mp4_path)

        # --- Construct FFmpeg Command ---
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite existing output file without asking
            "-loop",
            "1",  # Loop the image
            "-i",
            str(LOGO_PATH),  # Input 1: The fixed logo image
            "-i",
            str(input_aac_path),  # Input 2: The uploaded AAC audio file
            "-c:v",
            "libx264",  # Video encoder
            "-pix_fmt",
            "yuv420p",  # Ensure player compatibility (important for wide playback)
            "-c:a",
            "copy",  # Directly copy the audio stream, no re-encoding (very fast)
            "-shortest",  # Stop output when the shortest input stream (audio) ends
            str(output_mp4_path),
        ]

        # --- Execute FFmpeg ---
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_detail = stderr.decode().strip()
            raise HTTPException(
                status_code=500, detail=f"FFmpeg conversion failed: {error_detail}"
            )

        # --- Return File and Cleanup ---
        return FileResponse(
            path=output_mp4_path,
            media_type="video/mp4",
            filename=f"converted_{Path(audio_file.filename).stem}.mp4",
            background=BackgroundTask(cleanup_files, files_to_clean),
        )

    except Exception as e:
        # Ensure cleanup happens even on unexpected errors
        cleanup_files(files_to_clean)
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


async def _save_upload_file(upload_file: UploadFile, destination: Path):
    """Helper function to save an UploadFile to a destination."""
    contents = await upload_file.read()
    with open(destination, "wb") as f:
        f.write(contents)


@app.get("/", tags=["Root"])
def read_root():
    return {
        "message": "Welcome to the AAC to MP4 Converter API. Visit /docs for documentation."
    }
