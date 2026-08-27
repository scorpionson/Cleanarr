/**
 * API Handlers
 */

import axios from 'axios';

export const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:5000/";

const INFO_URL = `${BACKEND_URL}server/info`;
const DELETED_SIZES = `${BACKEND_URL}server/deleted-sizes`;
const DUPES_URL = `${BACKEND_URL}content/dupes`;
const SAMPLES_URL = `${BACKEND_URL}content/samples`;
const DELETE_MEDIA_URL = `${BACKEND_URL}delete/media`;
const IGNORE_MEDIA_URL = `${BACKEND_URL}content/ignore`;
const UNIGNORE_MEDIA_URL = `${BACKEND_URL}content/unignore`;
const ARR_STATUS_URL = `${BACKEND_URL}arr/status`;

export const getServerInfo = (): Promise<any> => {
  return axios.get(INFO_URL);
};

export const getDeletedSizes = (): Promise<any> => {
  return axios.get(DELETED_SIZES);
};

export const getDupeContent = (page: number = 1): Promise<any> => {
  return axios.get(`${DUPES_URL}?page=${page}`);
};

export const getSampleContent = (): Promise<any> => {
  return axios.get(SAMPLES_URL);
};

/**
 * Delete one copy of a piece of content.
 *
 * The backend rejects this with HTTP 409 when the copy is the one Radarr/Sonarr
 * currently tracks. Pass force to override that deliberately.
 */
export const deleteMedia = (library: string, contentKey: string, mediaId: number, force: boolean = false): Promise<any> => {
  return axios.post(DELETE_MEDIA_URL, {
    'library_name': library,
    'content_key': contentKey,
    'media_id': mediaId,
    'force': force
  })
};

export const getArrStatus = (): Promise<any> => {
  return axios.get(ARR_STATUS_URL);
};

export const ignoreMedia = (contentKey: string): Promise<any> => {
  return axios.post(IGNORE_MEDIA_URL, {
    'content_key': contentKey
  })
};

export const unIgnoreMedia = (contentKey: string): Promise<any> => {
  return axios.post(UNIGNORE_MEDIA_URL, {
    'content_key': contentKey
  })
};
