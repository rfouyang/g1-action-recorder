"""Map display: one entry for the 2D layers and the 3D scene."""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from loguru import logger

from component.map_display.layer_image import LayerImage
from component.map_display.scene_sync import SceneSync
from component.map_storage.service import MapDocument, MapStorage
from config.settings import MapViewerConfig, use_utf8_output


class MapDisplay:
    def __init__(self, **kwargs) -> None:
        self.layers = LayerImage(**kwargs)
        self.scene = SceneSync(**kwargs)

    @property
    def viewer_url(self) -> str:
        # MAP_VISER_PUBLIC_URL when the iframe must hit a dedicated Ingress host.
        viewer_url = MapViewerConfig.PUBLIC_URL or self.scene.url
        return viewer_url

    def start_viewer(self, document: MapDocument | None) -> None:
        """With no map open yet the 3D view starts empty; opening one builds it."""
        self.scene.start()
        if document is not None:
            self.scene.build(document)

    def build(self, document: MapDocument) -> None:
        """Another map was opened."""
        self.scene.build(document)

    def grid_png(self, document: MapDocument, which: str) -> bytes:
        png = self.layers.grid_png(document, which)
        return png

    def diff_png(self, document: MapDocument) -> bytes:
        png = self.layers.diff_png(document)
        return png

    def projection_png(self, document: MapDocument, z_lo_rel: float, z_hi_rel: float, source: str) -> bytes:
        png = self.layers.projection_png(document, z_lo_rel, z_hi_rel, source)
        return png

    def show_preview(self, document: MapDocument, erasure) -> None:
        self.scene.show_preview(document, erasure)

    def protection_png(self, protected) -> bytes:
        png = self.layers.protection_png(protected)
        return png

    def clear_preview(self) -> None:
        self.scene.clear_preview()

    def reload(self, document: MapDocument) -> None:
        """The document was replaced (restored original), not just edited."""
        self.scene.reload(document)

    def refresh(self, document: MapDocument) -> None:
        """After apply / undo / redo: drop the preview and redraw what changed."""
        self.scene.clear_preview()
        self.scene.refresh(document)

    @property
    def scene_layers(self) -> dict[str, bool]:
        layers = dict(self.scene.layers)
        return layers

    def set_scene_layer(self, name: str, visible: bool) -> None:
        self.scene.set_layer(name, visible)

    def highlight(self, document: MapDocument, outline: list, kind: str) -> None:
        self.scene.highlight(document, outline, kind)

    def focus(self, document: MapDocument, x: float, y: float, distance: float) -> None:
        self.scene.focus(document, x=x, y=y, distance=distance)


def demo_display() -> None:
    """Without start_viewer() the 3D calls are no-ops, so this runs without a viser server."""
    document = MapStorage().load()
    display = MapDisplay()
    png = display.projection_png(document, 0.10, 2.00, "map")
    display.refresh(document)
    logger.info("Projection {:,} bytes; refreshing without a 3D server does nothing", len(png))


def main() -> None:
    use_utf8_output()
    demo_display()


if __name__ == "__main__":
    main()
