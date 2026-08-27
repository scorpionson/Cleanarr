/**
 * What Radarr / Sonarr knows about one copy of a piece of content.
 *
 * Plex can hold several copies; the *arr only ever tracks one of them as "the"
 * file. The others are orphans - usually what you actually want to delete.
 */
export interface ArrInfo {
  /** True when an *arr tracks this exact file. */
  tracked: boolean,
  /** True when *arrs are configured but none of them tracks this file. */
  unmanaged?: boolean,
  /** Which configured instance tracks it, e.g. "Radarr" or "Radarr4K". */
  instance?: string,
  /** "radarr" | "sonarr" */
  type?: string,
  /** The path as the *arr sees it (may differ from the Plex path). */
  path?: string,
  /** Radarr/Sonarr custom format score for this file. Can be negative. */
  customFormatScore?: number | null,
  customFormats?: string[],
  quality?: string,
  size?: number,
}
