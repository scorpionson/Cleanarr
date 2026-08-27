import {majorScale, Pane, toaster} from "evergreen-ui";
import {autorun} from "mobx";
import {Observer} from "mobx-react-lite";
import React, {FunctionComponent, useCallback, useEffect, useState} from 'react';
import {deletedMediaContext, mediaContext} from "../stores/MediaStore";
import {Media, Content} from "../types";
import {bytesToSize, sumMediaSize} from "../util";
import {ContentItem} from "./ContentItem";
import {ContentList} from "./ContentList";
import {ContentTopBar} from "./ContentTopBar";
import {serverInfoContext} from "../stores/ServerInfoStore";
import {contentContext} from "../stores/ContentStore";

export const ContentPage:FunctionComponent<any> = () => {

  const listingTypes = [
    {
      label: 'Duplicates',
      value: 'duplicate'
    },
    {
      label: 'Samples',
      value: 'sample'
    },
  ];

  const [listingType, setListingType] = useState(listingTypes[0].value);

  const contentStore = React.useContext(contentContext);
  const mediaStore = React.useContext(mediaContext);
  const deletedMediaStore = React.useContext(deletedMediaContext);
  const serverInfoStore = React.useContext(serverInfoContext);

  useEffect(() => {
    onRefresh();
  });

  const onListingTypeChange = (listingType: string): void => {
    setListingType(listingType);
    onRefresh();
  };

  const onDeleteMedia = () => {
    toaster.warning(`Deleting ${mediaStore.length} items...`, {
      duration: 5,
      id: 'delete-toaster'
    });

    let promises: Promise<any>[] = [];
    const blocked: string[] = [];

    mediaStore.isDeleting = true;
    contentStore.items.forEach(movie => {
      movie.media.forEach(media => {
        if (media.id in mediaStore.media) {
          promises.push(
            mediaStore.deleteMedia(movie.library, movie.key, media).then(() => {
              deletedMediaStore.addMedia(media);
            }).catch((error) => {
              // Most likely the *arr guard. Report it and carry on with the rest
              // rather than failing the whole batch.
              blocked.push(error.message || 'Delete failed');
            })
          )
        }
      });
      promises.push(serverInfoStore.loadDeletedSizes());
    });

    Promise.all(promises).then(() => {
      mediaStore.isDeleting = false;
      if (blocked.length > 0) {
        toaster.danger(`${blocked.length} item(s) were not deleted: ${blocked[0]}`, {
          duration: 10,
          id: 'delete-toaster'
        });
      } else {
        toaster.success(`All items deleted!`, {
          duration: 5,
          id: 'delete-toaster'
        });
      }

      setTimeout(() => {
        onRefresh();
      }, 4500);
    });
  };

  const onRefresh = () => {
    mediaStore.reset();
    deletedMediaStore.reset();
    if (listingType === 'duplicate') {
      contentStore.loadDupeContent();
    } else if (listingType === 'sample') {
      contentStore.loadSampleMovies();
    }
    serverInfoStore.loadDeletedSizes();
  };

  const onDeselectAll = () => {
    mediaStore.reset();
  };

  const onResetSelection = useCallback(() => {
    contentStore.items.forEach((movie: Content) => {
      let _media = [
        ...movie.media
      ];
      // Rank the copies best-first. Whatever ends up at index 0 is kept and
      // everything below it is pre-checked for deletion, so this ordering
      // decides what the user is nudged to delete.
      const isTracked = (m: Media) => !!(m.arr && m.arr.tracked);

      let sortedMedia = _media.sort((a, b) => {
        // 1. Never rank the copy Radarr/Sonarr tracks below an untracked one.
        //    Size and resolution are poor proxies for "the right file": an
        //    orphan left behind by a failed upgrade is frequently the biggest
        //    copy, so ranking on size alone actively points at the wrong file.
        //    When no *arr is configured this is a no-op and the original
        //    resolution/size ordering below applies unchanged.
        const aTracked = isTracked(a) ? 0 : 1;
        const bTracked = isTracked(b) ? 0 : 1;
        if (aTracked !== bTracked) return aTracked - bTracked;

        // 2. Then prefer the higher resolution copy.
        if ((a.width || 0) !== (b.width || 0)) return (b.width || 0) - (a.width || 0);

        // 3. Then the larger file.
        return sumMediaSize(b) - sumMediaSize(a);
      });

      // Keep the top entry and pre-check the rest for removal - but never
      // pre-check a copy an *arr tracks, even if something else outranked it.
      sortedMedia.forEach(((media, index) => {
        if (index === 0) return;
        if (isTracked(media)) return;
        mediaStore.addMedia(media);
      }));
    });
  }, [mediaStore, contentStore.items]);


  useEffect(() => {
    // Determine the default media items to be removed
    autorun(() => {
      onResetSelection();
    });
  }, [onResetSelection]);

  const onInvertSelection = () => {
    contentStore.items.forEach(movie => {
      movie.media.forEach(media => {
        if (media.id in mediaStore.media) {
          mediaStore.removeMedia(media);
        } else {
          mediaStore.addMedia(media);
        }
      });
    });
  };

  const onDeleteMediaItem = (movie: Content, media: Media, force: boolean = false) => {
    toaster.warning(`Deleting item...`, {
      duration: 5,
      id: 'delete-toaster'
    });
    mediaStore.isDeleting = true;
    mediaStore.deleteMedia(movie.library, movie.key, media, force).then(() => {
      deletedMediaStore.addMedia(media);
      mediaStore.isDeleting = false;
      toaster.success(`Item deleted!`, {
        duration: 5,
        id: 'delete-toaster'
      });

      serverInfoStore.loadDeletedSizes();
    }).catch((error) => {
      mediaStore.isDeleting = false;
      toaster.danger(error.message || 'Failed to delete item', {
        duration: 10,
        id: 'delete-toaster'
      });
    })
  }

  const onIgnoreContent = (content: Content) => {
    contentStore.ignoreContent(content.key);
  }

  const onUnIgnoreContent = (content: Content) => {
    contentStore.unIgnoreContent(content.key);
  }

  const onChangeIncludeIgnored = (value: boolean) => {
    contentStore.setIncludeIgnore(value);
    if (!value) {
      contentStore.ignoredItems.forEach(movie => {
        movie.media.forEach(media => {
          if (media.id in mediaStore.media) {
            mediaStore.removeMedia(media);
          }
        });
      });
    }
  }

  const renderMovieList = () => (
    <Observer>
      {() => (
        <ContentList
          key={`${contentStore.length}_${contentStore.ignoredItems.length}`}
          loading={contentStore.loading}
          loadingFailed={contentStore.loadingFailed}
          loadingError={contentStore.loadingError}
          listingType={listingType}
          content={contentStore.items}
          renderContentItem={renderMovieItem}
        />
      )}
    </Observer>
  );

  const renderMovieItem = (movie: Content, key: number) => (
    <Observer key={key}>
      {() => (
        <ContentItem
          addMedia={(media: Media) => mediaStore.addMedia(media)}
          removeMedia={(media: Media) => mediaStore.removeMedia(media)}
          onDeleteMedia={onDeleteMediaItem}
          onIgnoreContent={onIgnoreContent}
          onUnIgnoreContent={onUnIgnoreContent}
          selectedMedia={mediaStore.media}
          deletedMedia={deletedMediaStore.media}
          content={movie}
        />
      )}
    </Observer>
  );

  const renderTopPane = () => {
    return (
      <Observer>
        {() => (
          <ContentTopBar
            loading={contentStore.loading}
            deleting={mediaStore.isDeleting}
            includeIgnored={contentStore.includeIgnored}
            numContent={contentStore.length}
            numSelected={mediaStore.length}
            totalSize={bytesToSize(mediaStore.totalSizeBytes)}
            onDeleteMedia={onDeleteMedia}
            onRefresh={onRefresh}
            listingOptions={listingTypes}
            listingType={listingType}
            onListingTypeChange={onListingTypeChange}
            onDeselectAll={onDeselectAll}
            onResetSelection={onResetSelection}
            onInvertSelection={onInvertSelection}
            onChangeIncludeIgnored={onChangeIncludeIgnored}
          />
        )}
      </Observer>
    )
  };

  return (
      <Observer>
        {() => (
          <Pane
            border="default"
            padding={majorScale(1)}
          >
            { renderTopPane() }
            { renderMovieList() }
          </Pane>
        )}
      </Observer>
  )
};
