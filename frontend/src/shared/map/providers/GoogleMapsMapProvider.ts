import type {
  CircleLayerOptions,
  GeoJsonSourceOptions,
  LatLng,
  LineLayerOptions,
  MapBounds,
  MapMarkerOptions,
  MapProvider,
  MapViewOptions,
  PointLayerOptions,
} from "../MapProvider";

/** `data-role="heading-arrow"` marks a marker element's child that receives heading rotation. */
const HEADING_ARROW_SELECTOR = '[data-role="heading-arrow"]';

declare global {
  interface Window {
    google?: any;
  }
}

/**
 * Loads the Google Maps JavaScript API script idempotently.
 */
function loadGoogleMapsScript(apiKey: string): Promise<void> {
  if (typeof window !== "undefined" && window.google?.maps) {
    return Promise.resolve();
  }

  const scriptId = "google-maps-js-sdk";
  const existing = document.getElementById(scriptId) as HTMLScriptElement | null;
  if (existing) {
    return new Promise((resolve, reject) => {
      if (window.google?.maps) {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () =>
        reject(new Error("Failed to load Google Maps script.")),
      );
    });
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.id = scriptId;
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(
      apiKey,
    )}&libraries=marker,geometry`;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () =>
      reject(
        new Error(
          "Failed to load Google Maps JavaScript API. Please check your internet connection and API key.",
        ),
      );
    document.head.appendChild(script);
  });
}

interface InternalMarker {
  id: string;
  position: LatLng;
  element?: HTMLElement;
  overlay?: any;
  infoWindow?: any;
  listeners: Array<() => void>;
}

/**
 * Google Maps JavaScript API implementation of {@link MapProvider}.
 * Provides seamless plug-and-play parity with MapboxMapProvider.
 */
export class GoogleMapsMapProvider implements MapProvider {
  private map: any = null;
  private markers = new Map<string, InternalMarker>();
  private sources = new Map<string, any>();
  private layers = new Map<string, string>(); // layerId -> sourceId
  private userPanZoomListeners = new Set<() => void>();
  private mapEventListeners: any[] = [];

  async mount(options: MapViewOptions): Promise<void> {
    if (!options.accessToken) {
      throw new Error("Google Maps API key is required but was not provided.");
    }

    await loadGoogleMapsScript(options.accessToken);

    const google = window.google;
    if (!google?.maps) {
      throw new Error("Google Maps JavaScript API was loaded but window.google.maps is unavailable.");
    }

    // Initialize Map with fleet-friendly clean styles (no POI noise, clean roadmap)
    this.map = new google.maps.Map(options.container, {
      center: { lat: options.center.lat, lng: options.center.lng },
      zoom: options.zoom,
      mapTypeId: google.maps.MapTypeId.ROADMAP,
      fullscreenControl: false,
      streetViewControl: false,
      mapTypeControl: false,
      zoomControl: true,
      zoomControlOptions: {
        position: google.maps.ControlPosition.RIGHT_CENTER,
      },
      styles: [
        {
          featureType: "poi",
          elementType: "labels",
          stylers: [{ visibility: "off" }],
        },
        {
          featureType: "transit",
          elementType: "labels.icon",
          stylers: [{ visibility: "off" }],
        },
      ],
    });

    // Track user drag/pan gestures
    const dragListener = this.map.addListener("dragstart", () => {
      this.userPanZoomListeners.forEach((fn) => fn());
    });
    this.mapEventListeners.push(dragListener);

    // Track user wheel / zoom gesture
    const container = options.container;
    const wheelHandler = () => {
      this.userPanZoomListeners.forEach((fn) => fn());
    };
    container.addEventListener("wheel", wheelHandler, { passive: true });
    this.mapEventListeners.push({
      remove: () => container.removeEventListener("wheel", wheelHandler),
    });
  }

  unmount(): void {
    this.markers.forEach((_, id) => this.removeMarker(id));
    this.markers.clear();

    this.sources.forEach((source) => {
      source.setMap(null);
    });
    this.sources.clear();
    this.layers.clear();

    this.mapEventListeners.forEach((listener) => {
      if (listener && typeof listener.remove === "function") {
        listener.remove();
      } else if (window.google?.maps?.event?.removeListener) {
        window.google.maps.event.removeListener(listener);
      }
    });
    this.mapEventListeners = [];
    this.userPanZoomListeners.clear();

    this.map = null;
  }

  setCenter(position: LatLng): void {
    this.requireMap().setCenter({ lat: position.lat, lng: position.lng });
  }

  setZoom(zoom: number): void {
    this.requireMap().setZoom(zoom);
  }

  fitBounds(bounds: MapBounds, paddingPx = 40): void {
    const google = window.google;
    const gBounds = new google.maps.LatLngBounds(
      { lat: bounds.sw.lat, lng: bounds.sw.lng },
      { lat: bounds.ne.lat, lng: bounds.ne.lng },
    );
    this.requireMap().fitBounds(gBounds, paddingPx);
  }

  addMarker(options: MapMarkerOptions): void {
    const google = window.google;
    const map = this.requireMap();

    let overlay: any = null;
    let infoWindow: any = null;
    const listeners: Array<() => void> = [];

    if (options.element) {
      // Use Custom OverlayView to place arbitrary DOM element into Google Maps pane
      class HTMLOverlay extends google.maps.OverlayView {
        private el: HTMLElement;
        private pos: any;

        constructor(el: HTMLElement, pos: LatLng) {
          super();
          this.el = el;
          this.pos = new google.maps.LatLng(pos.lat, pos.lng);
        }

        onAdd() {
          const panes = this.getPanes();
          panes?.overlayMouseTarget.appendChild(this.el);
        }

        draw() {
          const projection = this.getProjection();
          if (!projection) return;
          const point = projection.fromLatLngToDivPixel(this.pos);
          if (point) {
            this.el.style.position = "absolute";
            this.el.style.left = `${point.x}px`;
            this.el.style.top = `${point.y}px`;
            this.el.style.transform = "translate(-50%, -50%)";
          }
        }

        onRemove() {
          if (this.el.parentNode) {
            this.el.parentNode.removeChild(this.el);
          }
        }

        setPosition(newPos: LatLng) {
          this.pos = new google.maps.LatLng(newPos.lat, newPos.lng);
          this.draw();
        }
      }

      overlay = new HTMLOverlay(options.element, options.position);
      overlay.setMap(map);
      this._applyHeading(options.element, options.headingDeg);

      // Popup hover card handling
      if (options.popupHtml) {
        infoWindow = new google.maps.InfoWindow({
          content: options.popupHtml,
          disableAutoPan: true,
        });

        const enterHandler = () => {
          infoWindow.open({
            map,
            position: { lat: options.position.lat, lng: options.position.lng },
          });
        };
        const leaveHandler = () => {
          infoWindow.close();
        };

        options.element.addEventListener("mouseenter", enterHandler);
        options.element.addEventListener("mouseleave", leaveHandler);
        listeners.push(() => {
          options.element?.removeEventListener("mouseenter", enterHandler);
          options.element?.removeEventListener("mouseleave", leaveHandler);
        });
      }
    } else {
      // Fallback standard Google Maps Marker if no custom DOM element provided
      const marker = new google.maps.Marker({
        position: { lat: options.position.lat, lng: options.position.lng },
        map,
      });
      overlay = marker;
      if (options.popupHtml) {
        infoWindow = new google.maps.InfoWindow({ content: options.popupHtml });
      }
    }

    this.markers.set(options.id, {
      id: options.id,
      position: options.position,
      element: options.element,
      overlay,
      infoWindow,
      listeners,
    });
  }

  updateMarker(id: string, position: LatLng, headingDeg?: number): void {
    const item = this.markers.get(id);
    if (!item) return;

    item.position = position;
    if (item.overlay?.setPosition) {
      item.overlay.setPosition(position);
    }
    if (item.element) {
      this._applyHeading(item.element, headingDeg);
    }
    if (item.infoWindow && item.infoWindow.isOpen) {
      item.infoWindow.setPosition({ lat: position.lat, lng: position.lng });
    }
  }

  updateMarkerPopup(id: string, popupHtml: string): void {
    const item = this.markers.get(id);
    if (!item?.infoWindow) return;
    item.infoWindow.setContent(popupHtml);
  }

  removeMarker(id: string): void {
    const item = this.markers.get(id);
    if (!item) return;

    item.listeners.forEach((clean) => clean());
    item.infoWindow?.close();
    item.overlay?.setMap(null);
    this.markers.delete(id);
  }

  onMarkerClick(id: string, handler: () => void): void {
    const item = this.markers.get(id);
    if (!item) return;

    if (item.element) {
      item.element.addEventListener("click", handler);
      item.listeners.push(() => item.element?.removeEventListener("click", handler));
    } else if (item.overlay) {
      const gListener = item.overlay.addListener("click", handler);
      item.listeners.push(() => window.google?.maps?.event?.removeListener(gListener));
    }
  }

  addGeoJsonSource(options: GeoJsonSourceOptions): void {
    const google = window.google;
    const map = this.requireMap();

    // Remove existing if present
    if (this.sources.has(options.id)) {
      this.removeSource(options.id);
    }

    const dataLayer = new google.maps.Data();
    dataLayer.addGeoJson(options.data);
    dataLayer.setMap(map);

    this.sources.set(options.id, dataLayer);
  }

  addLineLayer(options: LineLayerOptions): void {
    const dataLayer = this.sources.get(options.sourceId);
    if (!dataLayer) return;

    this.layers.set(options.id, options.sourceId);
    dataLayer.setStyle({
      strokeColor: options.color ?? "#1E63FF",
      strokeWeight: options.widthPx ?? 4,
      strokeOpacity: 0.9,
    });
  }

  addCircleLayer(options: CircleLayerOptions): void {
    const dataLayer = this.sources.get(options.sourceId);
    if (!dataLayer) return;

    this.layers.set(options.id, options.sourceId);
    dataLayer.setStyle({
      fillColor: options.color ?? "#2FBF4F",
      fillOpacity: options.opacity ?? 0.15,
      strokeColor: options.color ?? "#2FBF4F",
      strokeWeight: 1.5,
      strokeOpacity: 0.6,
    });
  }

  addPointLayer(options: PointLayerOptions): void {
    const google = window.google;
    const dataLayer = this.sources.get(options.sourceId);
    if (!dataLayer) return;

    this.layers.set(options.id, options.sourceId);
    dataLayer.setStyle({
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: options.radiusPx ?? 6,
        fillColor: options.color ?? "#1E63FF",
        fillOpacity: 1.0,
        strokeColor: "#ffffff",
        strokeWeight: 2,
      },
    });
  }

  removeLayer(id: string): void {
    const sourceId = this.layers.get(id);
    if (sourceId) {
      const dataLayer = this.sources.get(sourceId);
      if (dataLayer) {
        dataLayer.setMap(null);
      }
      this.layers.delete(id);
    }
  }

  removeSource(id: string): void {
    const dataLayer = this.sources.get(id);
    if (dataLayer) {
      dataLayer.setMap(null);
      this.sources.delete(id);
    }
    // Remove references in layers
    for (const [layerId, srcId] of this.layers.entries()) {
      if (srcId === id) {
        this.layers.delete(layerId);
      }
    }
  }

  onUserPanOrZoom(handler: () => void): () => void {
    this.userPanZoomListeners.add(handler);
    return () => {
      this.userPanZoomListeners.delete(handler);
    };
  }

  private _applyHeading(element: HTMLElement | undefined, headingDeg: number | undefined): void {
    if (!element) return;
    const arrow = element.querySelector<HTMLElement>(HEADING_ARROW_SELECTOR);
    if (!arrow) return;
    if (headingDeg === undefined) {
      arrow.removeAttribute("data-visible");
      return;
    }
    arrow.style.transform = `rotate(${headingDeg}deg)`;
    arrow.setAttribute("data-visible", "true");
  }

  private requireMap(): any {
    if (!this.map) {
      throw new Error("GoogleMapsMapProvider: mount() must resolve before calling any other method.");
    }
    return this.map;
  }
}
