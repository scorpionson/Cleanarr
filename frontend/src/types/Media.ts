import {MediaPart} from "./MediaPart";
import {ArrInfo} from "./ArrInfo";

export interface Media {
  id: number,
  aspectRatio: number,
  audioChannels: number,
  audioCodec: string,
  bitrate: number,
  container: string,
  duration: number,
  width: number,
  height: number,
  has64bitOffsets?: boolean,
  optimizedForStreaming?: boolean,
  target?: string,
  title?: string,
  videoCodec: string,
  videoFrameRate: string,
  videoProfile: string,
  videoResolution: string,
  parts: MediaPart[],
  /** Present only when Radarr/Sonarr integration is configured. */
  arr?: ArrInfo
}
