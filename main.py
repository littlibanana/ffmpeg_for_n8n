import asyncio
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

# --- Application Settings ---
app = FastAPI(
    title="AAC to MP4 Converter",
    description="An API to convert AAC to MP4 using FastAPI and FFmpeg",
)

# Create a temporary directory to store uploaded and output files
TEMP_DIR = Path("temp_files")
TEMP_DIR.mkdir(exist_ok=True)


# --- FFmpeg Check ---
def check_ffmpeg_installed():
    """Checks if FFmpeg is installed and accessible in the system PATH during startup."""
    if not shutil.which("ffmpeg"):
        print("Error: FFmpeg is not installed or not in the system PATH.")
        print("Please install FFmpeg and ensure it's executable from the command line.")
        # In a cloud environment, this is typically done via 'apt-get install ffmpeg' or similar in a Dockerfile
        raise RuntimeError("FFmpeg not found in system's PATH.")


# --- Cleanup Function ---
def cleanup_files(paths: list[Path]):
    """Deletes the specified temporary files."""
    for path in paths:
        if path and path.exists():
            path.unlink()


# --- API Endpoint ---
@app.post("/convert-aac-to-mp4/", tags=["Conversion"])
async def convert_aac_to_mp4(
    audio_file: UploadFile = File(..., description="The AAC audio file to convert."),
    image_file: UploadFile = File("logo.png"),
):
    """
    Receives an AAC file and an optional image file, then converts them to an MP4 file.

    - **If only an audio file is provided**: The audio stream is directly encapsulated into an MP4 container (`-c:a copy`).
    - **If both audio and image files are provided**: A video will be generated using the image as the visual and the audio as the soundtrack.
    """
    check_ffmpeg_installed()

    job_id = str(uuid.uuid4())

    # Save the uploaded files to the temporary directory
    input_aac_path = TEMP_DIR / f"{job_id}_{audio_file.filename}"
    output_mp4_path = TEMP_DIR / f"{job_id}_output.mp4"

    try:
        # Save the audio file
        contents = await audio_file.read()
        with open(input_aac_path, "wb") as f:
            f.write(contents)

        input_image_path = None
        if image_file:
            # Save the image file
            input_image_path = TEMP_DIR / f"{job_id}_{image_file.filename}"
            image_contents = await image_file.read()
            with open(input_image_path, "wb") as f:
                f.write(image_contents)

        # Construct different FFmpeg commands based on whether an image is provided
        if input_image_path:
            # Scenario 2: Combine image and audio to generate a video
            cmd = [
                "ffmpeg",
                "-loop",
                "1",  # Loop the image
                "-i",
                str(input_image_path),  # Input 1: Image
                "-i",
                str(input_aac_path),  # Input 2: Audio
                "-c:v",
                "libx264",  # Video encoder
                "-tune",
                "stillimage",  # Optimize for still images
                "-c:a",
                "copy",  # Directly copy the audio stream, no re-encoding
                "-pix_fmt",
                "yuv420p",  # Ensure player compatibility
                "-shortest",  # Stop output when the shortest input stream (audio) ends
                "-y",  # Overwrite existing output file
                str(output_mp4_path),
            ]
        else:
            # Scenario 1: Only encapsulate AAC into an MP4 container
            cmd = [
                "ffmpeg",
                "-i",
                str(input_aac_path),
                "-c:a",
                "copy",  # Directly copy the audio codec, very fast
                "-y",
                str(output_mp4_path),
            ]

        # Execute FFmpeg asynchronously using asyncio.create_subprocess_exec to avoid blocking
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            # If FFmpeg execution fails, return an error message
            error_detail = stderr.decode().strip()
            print(f"FFmpeg Error: {error_detail}")
            raise HTTPException(
                status_code=500, detail=f"FFmpeg conversion failed: {error_detail}"
            )

        # Prepare cleanup tasks
        files_to_clean = [input_aac_path, output_mp4_path]
        if input_image_path:
            files_to_clean.append(input_image_path)

        # Return the file using FileResponse and perform cleanup in a background task
        return FileResponse(
            path=output_mp4_path,
            media_type="video/mp4",
            filename=f"converted_{Path(audio_file.filename).stem}.mp4",
            background=BackgroundTask(cleanup_files, files_to_clean),
        )

    except Exception as e:
        # Catch other potential errors
        # Note: 'input_image_path' needs to be checked for existence in locals()
        # to prevent UnboundLocalError if it was never assigned.
        cleanup_files(
            [
                input_aac_path,
                output_mp4_path,
                input_image_path if "input_image_path" in locals() else None,
            ]
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", tags=["Root"])
def read_root():
    return {
        "message": "Welcome to the AAC to MP4 Converter API. Please visit /docs for API documentation."
    }
