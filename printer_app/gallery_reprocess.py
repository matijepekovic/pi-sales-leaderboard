"""Cross-boundary gallery reprocess workflow; never creates or submits print jobs."""


class GalleryReprocessService:
    def __init__(self, gallery, routing):
        self.gallery = gallery
        self.routing = routing

    def reprocess(self, ident):
        job = self.gallery.import_job(ident)
        if not job:
            raise LookupError('This gallery job is unavailable.')
        if job['state'] not in ('COMPLETE', 'ERROR'):
            raise ValueError('Only completed or failed gallery jobs can be reprocessed.')
        source = self.routing.gallery_source(ident, job['filename'])
        reset = self.gallery.reprocess(ident)
        self.routing.requeue_gallery(source['message_id'], source['part'])
        return reset
