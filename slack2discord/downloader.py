import logging
from os import makedirs
from os.path import dirname, exists, isdir, join, realpath
from time import time

from requests import get

from .message import ParsedMessage, MessageFile


logger = logging.getLogger(__name__)


class SlackDownloader():
    """
    Download a list of previously parsed files attached to Slack messages.
    Once the files exist locally, they can then be uploaded to corresponding Discord messages.
    """
    def __init__(self,
                 parsed_messages: dict,
                 downloads_dir: str = None):
        # see SlackParser.parse() for details
        self.parsed_messages = parsed_messages

        if downloads_dir is None:
            # second level accuracy is probably sufficient
            # multiple callers shouldn't invoke this script within the same second
            downloads_dir = join(dirname(__file__), '..', 'downloads', str(int(time())))

        downloads_dir = realpath(downloads_dir)
        logger.info(f"Downloaded files from Slack (if any) will be placed in {downloads_dir}")
        if exists(downloads_dir):
            if isdir(downloads_dir):
                logger.warn(f"Downloads dir already exists: {downloads_dir}")
            else:
                error_msg = f"Downloads dir already exists but is **NOT** a dir: {downloads_dir}"
                logger.error(error_msg)
                raise RuntimeError(error_msg)

        # hold off on creating if it doesn't exist, only create if needed
        # (if parsing includes any files)
        self.downloads_dir = downloads_dir

        self.files: list[MessageFile] = []

    def _add_files(self, message: ParsedMessage) -> None:
        """
        Add to the list of self.files as appropriate for the given parsed message

        Each message can contain zero or more files

        self.files is modified in place, nothing is returned
        """
        for file in message.files:
            self.files.append(file)

    def _populate_files(self) -> None:
        """
        Populate the list of self.files to download

        Iterate through self.parsed_messages
        Find all of the messages that contain files

        self.files is modified in place, nothing is returned
        """
        # See SlackParser.parse() for more documentation on self.parsed_messages

        # keys are channel names, values are per-channel dicts
        for channel_msgs_dict in self.parsed_messages.values():
            # keys are timestamps, values are tuples
            # tuples containt ParsedMessage object and an optional dict for a thread
            for parsed_message, thread in channel_msgs_dict.values():
                self._add_files(parsed_message)
                if thread:
                    # if present, thread is a dict
                    # keys are timestamps, values are ParsedMessage objects
                    for thread_message in thread.values():
                        self._add_files(thread_message)

    def _wget(self, url, filename) -> None:
        """
        Fetch a file via HTTP GET from the given URL, and store it in the local filename.

        Nothing is returned on success.
        HTTP errors are raised as Exception's

        This is a simple implementation. We could instead stream data in chunks using
        Response.iter_content:
            https://requests.readthedocs.io/en/latest/api/#requests.Response.iter_content
        It is assumed that the files are in practice small enough that it's not worth it.

        We are unconditionally downloading the file. We could potentially try to determine if we
        already have the file (e.g. if a file exists locally of the same name, and its size in
        bytes matches the 'Content-Length:' header), but this is not currently
        implemented. Re-downloads will simply overwrite the previous contents, if made to the same
        downloads dir.

        This is a blocking call.
        """
        # We're basically emulating this wget command
        logger.debug(f"wget -O {filename} {url}")
        if exists(filename):
            logger.warning(f"local filename already exists, will overwrite: {filename}")

        with get(url) as req:
            req.raise_for_status()
            with open(filename, 'wb') as file:
                file.write(req.content)

    def download(self) -> None:
        """
        Download all of the files from parsed messages to the downloads dir.
        Create the downloads dir if needed.

        The downloads are all done sequentially. This could be made faster with aiohttp:
        https://docs.aiohttp.org/en/stable/
        """
        self._populate_files()

        if not self.files:
            logger.info("There are no files to download")
            return

        logger.info(
            f"There are {len(self.files)} files to download, will place in {self.downloads_dir}")
        if not exists(self.downloads_dir):
            makedirs(self.downloads_dir)

        for file in self.files:
            # using file.name would be more descriptive
            # but that risks filename collisions
            # we could place each file in its own dir, e.g. self.downloads_dir/file.id/file.name
            # but that would be more awkward to work with
            file.local_filename = join(self.downloads_dir, file.id)
            self._wget(file.url, file.local_filename)
        logger.info(f"Successfully downloaded {len(self.files)} files to {self.downloads_dir}")
