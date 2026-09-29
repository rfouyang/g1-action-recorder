"""Project configuration, split by domain."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def use_utf8_output() -> None:
    """Let Windows consoles print non-ASCII pose names; entry points call this first."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


class ServerConfig:
    HOST = os.getenv("G1_RECORDER_HOST", "127.0.0.1")
    PORT = int(os.getenv("G1_RECORDER_PORT", "8000"))
    LOG_LEVEL = "INFO"


class PathConfig:
    BASE_DIR = BASE_DIR
    ASSET_DIR = BASE_DIR / "asset" / "g1"
    URDF_PATH = ASSET_DIR / "g1_29dof_fake_hand.urdf"
    MJCF_PATH = ASSET_DIR / "g1_29dof_fake_hand.xml"
    METADATA_PATH = ASSET_DIR / "model_metadata.json"
    # A test run points this at a copy, so saving from the UI never touches the real poses.
    DATA_DIR = Path(os.getenv("G1_RECORDER_DATA_DIR", BASE_DIR / "data"))
    OUTPUT_DIR = BASE_DIR / "output"
    LOG_DIR = OUTPUT_DIR / "logs"
    # Demos write here and only here.
    DEMO_DIR = OUTPUT_DIR / "demo"


class RobotConfig:
    # Every action starts and ends here; it also seeds the robot at startup.
    HOME_POSE_NAME = "concierge_init"
    # Pelvis position of the free joint in the MJCF; the robot stands still, so it never moves.
    PELVIS_POSITION = (0.0, 0.0, 0.793)


class ActionConfig:
    SAMPLE_HZ = 25.0
    DEFAULT_TRAVEL_SECONDS = 1.0
    # Imported motions blend in from and out to the home pose over this long.
    IMPORT_BLEND_SECONDS = 1.0
    # Kimodo generates at 30 fps; a Kimodo NPZ that doesn't store its fps is read at this rate.
    KIMODO_FPS = 30.0
    PLAYBACK_TICK_SECONDS = 0.005



class PreviewConfig:
    """Pose pictures (saved beside each pose; Build action's picker): upper body from the front right, 2x size."""
    WIDTH = 240
    HEIGHT = 300
    BACKGROUND_RGB = (243, 244, 246)
    # MuJoCo free camera; the G1 faces +X, so azimuth 180 looks at its front.
    CAMERA = {"look_at": (0.0, 0.0, 1.02), "distance": 1.8, "azimuth": 160.0, "elevation": -8.0}


class ViewerConfig:
    HOST = os.getenv("G1_RECORDER_VISER_HOST", "127.0.0.1")
    PORT = int(os.getenv("G1_RECORDER_VISER_PORT", "8001"))
    # Browser-facing origin when it differs from hostname:port (e.g. a Kubernetes Ingress).
    PUBLIC_URL = (os.getenv("VISER_PUBLIC_URL", "").strip().rstrip("/") or None)
    UPDATE_HZ = 30.0
    # Robot-relative presets: the G1 faces +X, its own left is +Y.
    CAMERA_DISTANCE = 2.3
    CAMERA_HEIGHT = 0.91
    CAMERA_LOOK_AT = (0.0, 0.0, 0.68)
    CAMERA_FOV_DEGREES = 45.0
    CAMERA_MOVE_SECONDS = 0.6
    CAMERA_AZIMUTHS = {
        "front": 0.0,
        "front_left": 45.0,
        "left": 90.0,
        "back": 180.0,
        "right": 270.0,
        "front_right": 315.0,
    }


class SpeechConfig:
    # The G1 speaker plays 16 kHz mono 16-bit PCM; every clip is exactly that, whichever service made it.
    SAMPLE_RATE = 16000
    MAX_TEXT_CHARACTERS = 5000
    # Each toned part is one request to the service; this caps the cost of one Generate.
    MAX_REQUESTS = 50
    MAX_PAUSE_SECONDS = 10.0
    PAUSE_CHOICES = (0.25, 0.5, 1.0, 1.5)
    PRESET_FILE = BASE_DIR / "config" / "byteplus_presets.json"
    # Every voice's sample, made ahead by component/speech_generation/voice_samples.py --build.
    SAMPLE_DIR = PathConfig.DATA_DIR / "tts" / "sample"


class ByteplusTtsConfig:
    API_KEY = os.getenv("BYTEPLUS_API_KEY", "")
    URL = (os.getenv("BYTEPLUS_API_BASE_URL", "https://voice.ap-southeast-1.bytepluses.com")
           + "/api/v3/tts/unidirectional")
    RESOURCE_ID = os.getenv("BYTEPLUS_TTS_RESOURCE_ID", "seed-tts-2.0")
    USER_ID = "g1-action-recorder"
    TIMEOUT = (5.0, 60.0)
    DEFAULT_VOICE = "zh_male_m191_uranus_bigtts"
    # The official TTS 2.0 list with each voice's language and sample (docs: tts-voice-list); others by Voice ID.
    VOICE_FILE = BASE_DIR / "config" / "byteplus_voices.json"
    # speech_rate and loudness_rate: 0 is normal.
    RATE_RANGE = (-50, 100)


class MinimaxTtsConfig:
    API_KEY = os.getenv("MINIMAX_API_KEY", "")
    URL = os.getenv("MINIMAX_API_BASE_URL", "https://api.minimax.io") + "/v1/t2a_v2"
    TIMEOUT = (5.0, 90.0)
    MODELS = (("speech-2.8-hd", "High quality"), ("speech-2.8-turbo", "Fast"), ("speech-2.6-hd", ""),
              ("speech-2.6-turbo", ""), ("speech-02-hd", ""), ("speech-02-turbo", ""))
    DEFAULT_MODEL = "speech-2.8-hd"
    # Sound tags are read as sounds only by these models; others would say the word.
    SOUND_TAG_MODELS = ("speech-2.8-hd", "speech-2.8-turbo")
    DEFAULT_VOICE = "Chinese (Mandarin)_Reliable_Executive"
    # The account's list is read live (cached); this snapshot stands in without a key or network.
    VOICE_FILE = BASE_DIR / "config" / "minimax_voices.json"
    VOICE_CACHE_SECONDS = 600
    # Samples are made ahead with this model (one short request per voice).
    SAMPLE_MODEL = "speech-2.8-turbo"
    LANGUAGES = (("auto", "Auto detect"), ("Chinese", "Chinese"), ("Chinese,Yue", "Cantonese"), ("English", "English"),
                 ("Japanese", "Japanese"), ("Korean", "Korean"), ("Malay", "Malay"), ("Indonesian", "Indonesian"))
    # The UI's neutral is the API's calm.
    EMOTIONS = ("neutral", "happy", "sad", "angry", "fearful", "disgusted", "surprised", "fluent")
    SOUND_TAGS = ("laughs", "chuckle", "coughs", "clear-throat", "groans", "breath", "pant", "inhale", "exhale",
                  "gasps", "sniffs", "sighs", "snorts", "burps", "lip-smacking", "humming", "hissing", "emm",
                  "sneezes")
    SPEED_RANGE = (0.5, 2.0)
    PITCH_RANGE = (-12, 12)
    VOLUME_RANGE = (0.01, 10.0)


class MapPathConfig:
    # One folder per map (manifest.json, map.pcd, ground_map.pcd, grid.pgm, grid.yaml); uploads unpack here too.
    MAP_ROOT = PathConfig.DATA_DIR / "maps"
    # Name of the folder opened last, kept in MAP_ROOT; the next start opens it again.
    LAST_MAP_FILE = ".last_opened"
    # The sample map the demos copy from; they never write it.
    MAP_ID = "RTLAB"
    MAP_DIR = BASE_DIR / "data" / "maps" / MAP_ID
    # The files as they were before the first save: the only source for "Restore original", never overwritten.
    ORIGINAL_SUFFIX = ".orig"
    BACKUP_DIR_NAME = ".backup"
    # What was done in each editing session, written on save; the robot ignores it.
    EDIT_LOG_FILE = "edits.json"
    # A copy of every map zip Save & export downloads.
    PACKAGE_DIR = PathConfig.OUTPUT_DIR / "map_exports"
    DEMO_DIR = PathConfig.DEMO_DIR / "map"


class MapGridConfig:
    # Fixed names: the G1 map package (g1_api MAP_FILES) knows the grid by these.
    GRID_FILE = "grid.pgm"
    YAML_FILE = "grid.yaml"
    FREE = 254
    OCCUPIED = 0
    UNKNOWN = 205
    VALUES = (OCCUPIED, UNKNOWN, FREE)


class MapCloudConfig:
    MAP_FILE = "map.pcd"
    GROUND_FILE = "ground_map.pcd"
    # Every height band is above the floor measured per map and per cell (map_storage/floor_height.py).
    # Above the floor so the ground stays, below the ceiling so it stays too.
    ERASE_Z_RANGE_REL = (0.10, 2.00)
    # ground_map.pcd reaches ~2 m above the floor like map.pcd, so it gets the same band.
    GROUND_ERASE_Z_RANGE_REL = (0.10, 2.00)
    PROJECTION_Z_RANGE_REL = (0.10, 2.00)
    # Per-cell floor: tile size, where around the building floor to look, points a tile needs, histogram bin.
    FLOOR_TILE_M = 0.5
    FLOOR_SEARCH_REL = (-0.20, 0.50)
    FLOOR_MIN_POINTS = 20
    FLOOR_BIN_M = 0.02
    # A height bin counts as a layer when it holds this share of the tile's busiest bin.
    FLOOR_DENSE_SHARE = 0.25
    # A tile whose floor lands outside this band around the building floor is not floor.
    FLOOR_PLAUSIBLE_REL = (-0.10, 0.30)


class MapEditConfig:
    # Two cells: a one-cell diagonal leaves corner gaps an 8-neighbour planner slips through.
    WALL_WIDTH_M = 0.10
    BRUSH_RADIUS_M = 0.15
    ERASE_GRID_VALUE = MapGridConfig.FREE
    TOOL_NAMES = {
        "lasso_erase": "Lasso erase",
        "rect_erase": "Rectangle erase",
        "brush_erase": "Brush erase",
        "polyline_wall": "Wall",
        "polygon_fill": "Polygon",
        "rect_fill": "Rectangle",
        "obstacle_brush": "Obstacle brush",
        "candidate_erase": "Clear candidate",
        "candidate_fill": "Fill candidate",
    }


class MapInspectionConfig:
    # Wall segments shorter than this (pixels) are left out of the direction estimate.
    DIRECTION_MIN_LENGTH_PX = 20
    DIRECTION_BIN_DEG = 1.0
    # Snapping on the page: end points and existing walls within this distance pull the cursor.
    SNAP_RADIUS_M = 0.15
    # Candidates: the band is what the robot can bump into, above the local floor.
    CANDIDATE_Z_RANGE_REL = (0.10, 1.50)
    CANDIDATE_MIN_POINTS = 3
    CANDIDATE_MIN_CELLS = 6
    # A grid obstacle counts as supported if cloud points lie within this many cells of it.
    CANDIDATE_GHOST_MARGIN_CELLS = 2
    # Protected zone: cells with at least PROTECT_MIN_POINTS points above this height are static structure;
    # the zone reaches PROTECT_MARGIN_CELLS further.
    PROTECT_MIN_HEIGHT_REL = 2.10
    PROTECT_MIN_POINTS = 2
    PROTECT_MARGIN_CELLS = 2
    # Deleting more protected points than this asks once more.
    PROTECT_WARN_POINTS = 50


class MapDisplayConfig:
    PROJECTION_COLOR = (220, 38, 38)
    # A cell reaches full opacity at this many points: walls read solid, a stray point stays faint.
    PROJECTION_FULL_COUNT = 5
    # Changed-cell highlight (RGBA): obstacle cleared, obstacle added, anything else.
    DIFF_COLORS = {"cleared": (20, 184, 166, 200), "added": (249, 115, 22, 230), "other": (139, 92, 246, 200)}
    PROTECTION_COLOR = (234, 179, 8, 110)


class MapViewerConfig:
    HOST = os.getenv("G1_RECORDER_MAP_VISER_HOST", "127.0.0.1")
    # Its own Viser server, so the robot view is never disturbed by a map.
    PORT = int(os.getenv("G1_RECORDER_MAP_VISER_PORT", "8002"))
    # When set (Kubernetes Ingress), the map iframe uses this instead of hostname:PORT.
    PUBLIC_URL = (os.getenv("MAP_VISER_PUBLIC_URL", "").strip().rstrip("/") or None)
    VOXEL_SIZE = 0.08
    POINT_SIZE = 0.04
    PREVIEW_POINT_SIZE = 0.06
    # Heights (above the floor) spanning the colour ramp of the cloud.
    COLOR_Z_RANGE_REL = (0.0, 2.5)
    # Red preview points are drawn at full resolution up to this many; the count reported is always the full one.
    PREVIEW_LIMIT = 200_000
    PREVIEW_COLOR = (255, 0, 0)
    PROTECTED_COLOR = (255, 0, 255)
    # The candidate picked on the Check tab: a fence from the floor to this height, in its kind's colour.
    HIGHLIGHT_HEIGHT_REL = 1.8
    HIGHLIGHT_THICKNESS = 0.05
    # Brighter than the 2D colours: they must stand out from the height-coloured points.
    HIGHLIGHT_COLORS = {"ghost": (240, 60, 255), "missing": (0, 190, 255)}


def demo_settings() -> None:
    print(f"Data: {PathConfig.DATA_DIR}")
    print(f"Page: http://{ServerConfig.HOST}:{ServerConfig.PORT}  3D: http://{ViewerConfig.HOST}:{ViewerConfig.PORT}")
    print(f"Speech keys set: BytePlus {bool(ByteplusTtsConfig.API_KEY)}, MiniMax {bool(MinimaxTtsConfig.API_KEY)}")


def main() -> None:
    use_utf8_output()
    demo_settings()


if __name__ == "__main__":
    main()
