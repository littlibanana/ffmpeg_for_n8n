import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

# --- Application Settings ---
app = FastAPI(
    title="AAC to MP4 Converter with Subtitles",
    description="An API to convert AAC to MP4, optionally adding SRT subtitles using a fixed image logo.png.",
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


# --- FFmpeg Utility ---
def escape_ffmpeg_path(path_str: str) -> str:
    """Escapes a path for use in FFmpeg filters (e.g., subtitles)."""
    # For Windows paths primarily, but good practice.
    # FFmpeg filters can be picky about colons and backslashes.
    return path_str.replace("\\", "/").replace(":", "\\:")


# --- API Endpoint ---
@app.post("/convert/", tags=["Conversion"])
async def convert_to_mp4_with_subtitles(
    audio_file: UploadFile = File(..., description="The AAC audio file to convert."),
    subtitle_file: Optional[UploadFile] = File(
        None, description="Optional SRT subtitle file to add."
    ),
    subtitle_mode: str = Query(
        "hard",
        enum=["hard", "soft"],
        description="Subtitle mode: 'hard' (burned into video) or 'soft' (embed as a switchable track).",
    ),
):
    """
    Converts an AAC file to an MP4 video using a fixed 'logo.png' image,
    with optional SRT subtitles.

    - **With Subtitles (Hard)**: Burns subtitles directly into the video (requires 'logo.png').
    - **With Subtitles (Soft)**: Adds subtitles as a selectable track (requires 'logo.png').
    """
    job_id = str(uuid.uuid4())
    files_to_clean = []

    try:
        # --- Save Uploaded Files ---
        input_aac_path = TEMP_DIR / f"{job_id}_{audio_file.filename}"
        await _save_upload_file(audio_file, input_aac_path)
        files_to_clean.append(input_aac_path)

        input_srt_path = None
        if subtitle_file:
            input_srt_path = TEMP_DIR / f"{job_id}_{subtitle_file.filename}"
            await _save_upload_file(subtitle_file, input_srt_path)
            files_to_clean.append(input_srt_path)

        output_mp4_path = TEMP_DIR / f"{job_id}_output.mp4"
        files_to_clean.append(output_mp4_path)

        # --- Construct FFmpeg Command ---
        cmd = ["ffmpeg"]

        # Always use logo.png as the image input
        cmd.extend(["-loop", "1", "-i", str(LOGO_PATH)])
        cmd.extend(["-i", str(input_aac_path)])

        if input_srt_path and subtitle_mode == "soft":
            cmd.extend(["-i", str(input_srt_path)])

        # Video and Audio Codec Settings (always creating video with logo)
        cmd.extend(["-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p"])
        cmd.extend(["-c:a", "copy"])

        # --- Subtitle Settings ---
        if input_srt_path:
            if subtitle_mode == "hard":
                # Hardsubbing uses a video filter
                escaped_srt_path = escape_ffmpeg_path(str(input_srt_path))
                cmd.extend(["-vf", f"subtitles={escaped_srt_path}"])
            else:  # soft
                # Softsubbing copies the subtitle stream into the container
                cmd.extend(["-c:s", "mov_text", "-metadata:s:s:0", "language=eng"])

        # --- Final Command Arguments ---
        cmd.append(
            "-shortest"
        )  # Stop output when the shortest input stream (audio) ends
        cmd.extend(["-y", str(output_mp4_path)])  # Overwrite existing output file

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
