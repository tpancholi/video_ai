from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import ffmpeg
from pydantic import BaseModel, Field
from tinytag import TinyTag

# from ffmpeg import Error as FFmpegError # Uncomment if you prefer an explicit import for the error

# --- Setup Logging ---
# Configure the logger once at the start of the script
# In a real application, you might configure this via a config file (e.g., logging.conf)
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {
    "FFprobe (Technical Data - HIGH Support)": [
        ".mov",
        ".mp4",
        ".mkv",
        ".avi",
        ".webm",
        ".ts",
        ".mxf",
        " & many more...",
    ],
    "TinyTag (Simple Tags - LIMITED Support)": [".mp3", ".m4a", ".flac", ".wav", ".ogg", ".wma", ".mp4"],
}
logger.info("--- Supported Formats Overview ---")
for tool, formats in SUPPORTED_FORMATS.items():
    logger.info("  %s: %s", tool, ", ".join(formats))
logger.info("----------------------------------")


# --- Pydantic Data Models (Schema) ---


class VideoStreamMetadata(BaseModel):
    """Technical details for the primary video stream (from ffprobe)."""

    codec_name: str = Field(description="Video codec (e.g., h264, vp9).")
    profile: str = Field(description="Codec profile (e.g., High, Main).")
    width: int
    height: int
    bit_rate: int = Field(description="Video stream bitrate in bits/s.")
    avg_frame_rate: float = Field(description="Average frames per second (e.g., 29.97).")
    pixel_format: str = Field(description="Pixel format (e.g., yuv420p).")


class AudioStreamMetadata(BaseModel):
    """Technical details for the primary audio stream (from ffprobe)."""

    codec_name: str = Field(description="Audio codec (e.g., aac, mp3).")
    sample_rate: int = Field(description="Sample rate in Hz.")
    channels: int = Field(description="Number of audio channels.")
    bit_rate: int = Field(description="Audio stream bitrate in bits/s.")
    channel_layout: str = Field(description="Channel configuration (e.g., stereo, 5.1).")


class ContentCreatorMetadata(BaseModel):
    """
    Comprehensive metadata model for content creators, combining tinytag and ffprobe data.
    """

    # 1. Essential File Info (from tinytag / OS)
    file_path: Path = Field(description="The absolute path to the video file.")
    filename: str
    filesize_bytes: int = Field(description="File size in bytes.")

    # 2. Descriptive Tags (primarily from tinytag/ffprobe tags)
    title: str | None = Field(None, description="The video's embedded title/name.")
    artist: str | None = Field(None, description="The content creator's name or tag.")
    year: str | None = Field(None, description="Year the content was created.")

    # 3. Time and Size Metrics
    duration_seconds: float = Field(description="Total video duration in seconds.")
    duration_friendly: str = Field(description="Total duration in H:MM:SS format.")
    overall_bitrate_kbps: int = Field(description="Total bitrate (video + audio) in kbps.")

    # 4. Technical Stream Details (from ffprobe)
    video_stream: VideoStreamMetadata | None = Field(None, description="Details of the main video stream.")
    audio_stream: AudioStreamMetadata | None = Field(None, description="Details of the main audio stream.")

    # 5. Raw/Extra Tags (for completeness)
    raw_tags: dict[str, Any] = Field({}, description="Other embedded tags (e.g., encoder, creation_time).")


# --- Helper Functions ---


def _convert_duration(seconds: float) -> str:
    """Converts seconds to HH:MM:SS format."""
    hours = math.floor(seconds / 3600)
    minutes = math.floor((seconds % 3600) / 60)
    seconds_remainder = round(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_remainder:02d}"


def _extract_ffprobe_data(file_path: Path) -> dict[str, Any]:
    """Runs ffprobe on the file and returns the parsed JSON dict."""
    try:
        logger.info("Running ffprobe on %s...", file_path.name)
        probe_data = ffmpeg.probe(filename=str(file_path))
    except ffmpeg.Error as e:
        # Use logging.error to report the ffprobe failure and stderr output
        err_msg = f"Error running ffprobe on {file_path.name}: {e.stderr.decode('utf8')}"
        logger.exception(err_msg.strip())
        return {}
    else:
        logger.info("ffprobe successful for %s.", file_path.name)
        return probe_data


# --- Main Extraction Function ---


def get_video_metadata(file_path: Path) -> ContentCreatorMetadata | None:
    """
    Extracts comprehensive video metadata using both tinytag and ffmpeg-python
    and validates it using the Pydantic model.
    """
    path = Path(file_path).resolve()
    logger.info("Validating input file: %s", path)
    if not path.exists():
        # Raise an exception since this is a critical input failure
        err_msg = f"Input file not found: {path}"
        raise FileNotFoundError(err_msg.strip())

    logger.info("Processing file: %s", path.name)

    # 1. Use tinytag for basic info and simple descriptive tags
    tag = None
    try:
        tag = TinyTag.get(str(path))
        logger.info("Successfully extracted basic tags using TinyTag.")
    except Exception:
        # Use logging.exception to log the full traceback for unexpected tinytag errors
        err_msg = f"TinyTag Error: Could not read basic tags from {path.name}."
        logger.warning(err_msg.strip())

    # 2. Use ffprobe for detailed technical stream data
    logger.info("Path %s", path)
    ffprobe_data = _extract_ffprobe_data(path)

    video_stream_data, audio_stream_data = None, None
    format_info = ffprobe_data.get("format", {})

    # Iterate through streams to find the primary video/audio stream
    for stream in ffprobe_data.get("streams", []):
        try:
            if stream.get("codec_type") == "video" and not video_stream_data:
                # Safely extract and convert common video fields
                avg_frame_rate_str = stream.get("avg_frame_rate", "0/1")
                num, den = map(int, avg_frame_rate_str.split("/"))

                video_stream_data = VideoStreamMetadata(
                    codec_name=stream.get("codec_name", "N/A"),
                    profile=stream.get("profile", "N/A"),
                    width=stream.get("width", 0),
                    height=stream.get("height", 0),
                    # ffprobe bit_rate is often a string, ensure it's converted to int
                    bit_rate=int(stream.get("bit_rate", 0)),
                    avg_frame_rate=(num / den) if den else 0.0,
                    pixel_format=stream.get("pix_fmt", "N/A"),
                )
                logger.debug("Video stream metadata extracted.")

            elif stream.get("codec_type") == "audio" and not audio_stream_data:
                audio_stream_data = AudioStreamMetadata(
                    codec_name=stream.get("codec_name", "N/A"),
                    sample_rate=int(stream.get("sample_rate", 0)),
                    channels=stream.get("channels", 0),
                    bit_rate=int(stream.get("bit_rate", 0)),
                    channel_layout=stream.get("channel_layout", "N/A"),
                )
                logger.debug("Audio stream metadata extracted.")
        except Exception:
            # Catch errors during stream processing (e.g., bad cast to int)
            err_msg = f"Error processing stream in {path.name}. Stream data: {stream}"
            logger.exception(err_msg.strip())

    # 3. Consolidate and build the final Pydantic model
    try:
        ffprobe_duration = float(format_info.get("duration", 0.0))
    except Exception:
        # Catch errors during final Pydantic validation/mapping
        err_msg = f"Error validating metadata in {path.name}."
        logger.exception(err_msg.strip())
        return None
    else:
        if ffprobe_duration > 0.0:
            overall_duration = ffprobe_duration
        elif tag and tag.duration:
            overall_duration = tag.duration
        else:
            overall_duration = 0.0
        overall_duration = float(overall_duration)
        metadata = ContentCreatorMetadata(
            file_path=path,
            filename=path.name,
            filesize_bytes=path.stat().st_size,
            title=tag.title if tag else None,
            artist=tag.artist if tag else None,
            year=tag.year if tag else None,
            duration_seconds=overall_duration,
            duration_friendly=_convert_duration(overall_duration),
            overall_bitrate_kbps=int(format_info.get("bit_rate", 0)) // 1000,
            video_stream=video_stream_data,
            audio_stream=audio_stream_data,
            raw_tags=format_info.get("tags", {}),
        )
        logger.info("Metadata successfully validated by Pydantic for %s.", path.name)
        return metadata


# --- Example Usage ---

if __name__ == "__main__":
    # NOTE: You MUST replace this with a valid path to an actual video file on your system
    BASE_DIR = Path(__file__).resolve().parent
    VIDEO_FILE_PATH = BASE_DIR / "data" / "meeting_recording_video.mov"

    if not Path(VIDEO_FILE_PATH).exists():
        logger.warning(
            "The placeholder path is not valid. Please replace 'path/to/your/test_video.mp4' with an actual file path."
        )

    try:
        metadata = get_video_metadata(VIDEO_FILE_PATH)

        if metadata:
            logger.info("--- Metadata Extraction Summary ---")

            # Use JSON dump for easy inspection of the full validated object
            metadata_dict = metadata.model_dump()
            if metadata_dict.get("file_path"):
                metadata_dict["file_path"] = str(metadata_dict["file_path"])
            metadata_json = json.dumps(metadata_dict, indent=4)
            logger.info("Full Pydantic Metadata:\n%s", metadata_json)

            logger.info("--- Creator Quick View ---")
            logger.info("Title: %s", metadata.title or metadata.filename)
            if metadata.video_stream:
                logger.info("Resolution: %dx%d", metadata.video_stream.width, metadata.video_stream.height)
                logger.info("FPS: %.2f", metadata.video_stream.avg_frame_rate)
                logger.info("Video Codec: %s", metadata.video_stream.codec_name)
            else:
                logger.warning("Video stream details are missing from FFprobe output.")

            logger.info("Duration: %s", metadata.duration_friendly)
            logger.info("Overall Bitrate: %d Kbps", metadata.overall_bitrate_kbps)

    except FileNotFoundError as e:
        err_msg = f"FATAL ERROR: Input file not found: {e}"
        logger.critical(err_msg.strip())
    except Exception:
        err_msg = "An unhandled exception occurred in the main execution block."
        logger.exception(err_msg)
