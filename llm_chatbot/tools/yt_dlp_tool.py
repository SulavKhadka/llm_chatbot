from typing import Optional, Dict, Union, List
from pathlib import Path
from datetime import datetime
from enum import Enum
import logging
from pydantic import BaseModel, Field, validator, HttpUrl
import yt_dlp
import inspect

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class VideoFormat(BaseModel):
    """Represents a video format option."""
    format_id: str = Field(..., description="Format identifier")
    ext: str = Field(..., description="File extension")
    resolution: Optional[str] = Field(None, description="Video resolution")
    filesize: Optional[int] = Field(None, description="File size in bytes")
    tbr: Optional[float] = Field(None, description="Total bitrate in KBit/s")
    format_note: Optional[str] = Field(None, description="Additional format info")
    vcodec: Optional[str] = Field(None, description="Video codec")
    acodec: Optional[str] = Field(None, description="Audio codec")
    
    class Config:
        extra = "allow"  # Allow additional fields from yt-dlp

class VideoInfo(BaseModel):
    """Represents video metadata."""
    id: str = Field(..., description="Video identifier")
    title: str = Field(..., description="Video title")
    description: Optional[str] = Field(None, description="Video description")
    duration: Optional[int] = Field(None, description="Duration in seconds")
    view_count: Optional[int] = Field(None, description="View count")
    uploader: Optional[str] = Field(None, description="Uploader name")
    upload_date: Optional[str] = Field(None, description="Upload date")
    formats: List[VideoFormat] = Field(default_factory=list, description="Available formats")
    webpage_url: HttpUrl = Field(..., description="Video URL")
    
    class Config:
        extra = "allow"

class DownloadResult(BaseModel):
    """Represents the result of a download operation."""
    filepath: Path = Field(..., description="Path to the downloaded file")
    format_id: str = Field(..., description="Format ID used for download")
    filesize: Optional[int] = Field(None, description="Size of downloaded file in bytes")
    error: Optional[str] = Field(None, description="Error message if any")
    success: bool = Field(..., description="Whether download was successful")

class AudioFormat(str, Enum):
    """Supported audio formats."""
    MP3 = "mp3"
    M4A = "m4a"
    WAV = "wav"
    OPUS = "opus"
    VORBIS = "vorbis"

class YtDLPError(Exception):
    """Base exception for YtDLPTool errors."""
    pass

class YtDLPTool:
    """Enhanced interface for yt-dlp operations with Pydantic models and error handling. Useful for downloading and or searching for youtube videos/metadata and or audio in many formats and qualities."""
    
    def __init__(self, output_path: Optional[str] = None):
        """
        Initialize YtDLPTool with optional output path.
        
        Args:
            output_path: Directory where downloads will be saved. Defaults to current directory.
        """
        self.output_path = Path(output_path or ".")
        try:
            self.output_path.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise YtDLPError(f"Cannot create output directory: Permission denied - {str(e)}")
        except Exception as e:
            raise YtDLPError(f"Failed to create output directory: {str(e)}")
        
        logger.info(f"Initialized YtDLPTool with output path: {self.output_path}")

    def _get_available_methods(self) -> List[Dict[str, str]]:
        """
        Returns a list of all public methods in the class along with their docstrings.
        
        Returns:
            List of dictionaries containing method names and their documentation.
            Each dictionary has:
                - name: Method name
                - docstring: Method documentation
                - signature: Method signature
        """
        methods = []
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            # Skip private methods (those starting with _)
            if not name.startswith('_'):
                # Get the method's signature
                signature = str(inspect.signature(method))
                # Get the method's docstring, clean it up and handle None case
                docstring = inspect.getdoc(method) or "No documentation available"
                
                methods.append({
                    "name": name,
                    "docstring": docstring,
                    "signature": f"{name}{signature}",
                    "func": method
                })
        
        return sorted(methods, key=lambda x: x["name"])

    def _get_base_options(self) -> Dict:
        """Get base options for yt-dlp."""
        return {
            'quiet': False,
            'no_warnings': False,
            'paths': {'home': str(self.output_path)},
            'nocheckcertificate': False,  # Enforce certificate checking
            'socket_timeout': 30,  # Timeout for network operations
        }

    def extract_info(self, url: str) -> VideoInfo:
        """
        Extract metadata information about the youtube video without downloading.
        
        Args:
            url: URL of the video
            
        Returns:
            VideoInfo object containing video metadata
        """
        try:
            options = self._get_base_options()
            options.update({
                'extract_flat': True,
                'dump_single_json': True,
                'format': None
            })
            
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
                sanitized_info = ydl.sanitize_info(info)
                return VideoInfo.parse_obj(sanitized_info)
                
        except yt_dlp.utils.DownloadError as e:
            raise YtDLPError(f"Failed to extract video info: {str(e)}")
        except Exception as e:
            raise YtDLPError(f"Unexpected error during info extraction: {str(e)}")

    def download_video(
        self, 
        url: str, 
        format_id: Optional[str] = None, 
        filename_template: Optional[str] = None
    ) -> DownloadResult:
        """
        Download a youtube video in specified format.
        
        Args:
            url: URL of the video
            format_id: Format ID or quality specification
            filename_template: Custom filename template
            
        Returns:
            DownloadResult object with download details
        """
        try:
            options = self._get_base_options()
            options.update({
                'format': format_id or 'bestvideo+bestaudio/best',
                'merge_output_format': 'mp4',
                'writethumbnail': True,
            })
            
            if filename_template:
                options['outtmpl'] = {'default': f'{filename_template}.%(ext)s'}
            
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = Path(ydl.prepare_filename(info))
                
                return DownloadResult(
                    filepath=filepath,
                    format_id=info.get('format_id', 'N/A'),
                    filesize=filepath.stat().st_size if filepath.exists() else None,
                    success=True,
                    error=None
                )
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            logger.error(f"Download failed: {error_msg}")
            return DownloadResult(
                filepath=Path(""),
                format_id=format_id or "N/A",
                success=False,
                error=error_msg
            )
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.error(error_msg)
            return DownloadResult(
                filepath=Path(""),
                format_id=format_id or "N/A",
                success=False,
                error=error_msg
            )

    def download_audio(
        self, 
        url: str, 
        audio_format: AudioFormat = AudioFormat.MP3, 
        audio_quality: str = "192"
    ) -> DownloadResult:
        """
        Download audio from a youtube video.
        
        Args:
            url: URL of the video
            audio_format: Output audio format
            audio_quality: Audio quality in kbps
            
        Returns:
            DownloadResult object with download details
        """
        try:
            options = self._get_base_options()
            options.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': audio_format.value,
                    'preferredquality': audio_quality,
                }],
                'outtmpl': {'default': '%(title)s.%(ext)s'},
            })
            
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = Path(self.output_path) / f"{info['title']}.{audio_format.value}"
                
                return DownloadResult(
                    filepath=filepath,
                    format_id=f"audio-{audio_format.value}",
                    filesize=filepath.stat().st_size if filepath.exists() else None,
                    success=True,
                    error=None
                )
                
        except Exception as e:
            error_msg = f"Audio download failed: {str(e)}"
            logger.error(error_msg)
            return DownloadResult(
                filepath=Path(""),
                format_id=f"audio-{audio_format.value}",
                success=False,
                error=error_msg
            )

    def list_formats(self, url: str) -> List[VideoFormat]:
        """
        List all available formats for a yputube video.
        
        Args:
            url: URL of the video
            
        Returns:
            List of VideoFormat objects
            
        Raises:
            YtDLPError: If format listing fails
        """
        try:
            info = self.extract_info(url)
            return [VideoFormat.parse_obj(format_info) for format_info in info.formats]
        except Exception as e:
            raise YtDLPError(f"Failed to list formats: {str(e)}")

    def download_with_subtitle(
        self, 
        url: str, 
        subtitle_langs: Optional[List[str]] = None
    ) -> DownloadResult:
        """
        Download youtube video with subtitles.
        
        Args:
            url: URL of the video
            subtitle_langs: List of language codes for subtitles
            
        Returns:
            DownloadResult object with download details
        """
        try:
            options = self._get_base_options()
            options.update({
                'format': 'bestvideo+bestaudio/best',
                'writesubtitles': True,
                'subtitleslangs': subtitle_langs or ['en'],
                'embedsubtitles': True,
                'merge_output_format': 'mp4',
            })
            
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = Path(ydl.prepare_filename(info))
                
                return DownloadResult(
                    filepath=filepath,
                    format_id=info.get('format_id', 'N/A'),
                    filesize=filepath.stat().st_size if filepath.exists() else None,
                    success=True,
                    error=None
                )
                
        except Exception as e:
            error_msg = f"Subtitle download failed: {str(e)}"
            logger.error(error_msg)
            return DownloadResult(
                filepath=Path(""),
                format_id="N/A",
                success=False,
                error=error_msg
            )