"""Reader that processes MyST Markdown and returns HTML5."""
import json
import math
import os

import bs4
from mwc.counter import count_words_in_markdown
from yaml import safe_load

from myst_parser import main

from pelican import signals
from pelican.readers import BaseReader
from pelican.utils import pelican_open

DIR_PATH = os.path.dirname(__file__)
TEMPLATES_PATH = os.path.abspath(os.path.join(DIR_PATH, "templates"))
MYST_READER_HTML_TEMPLATE = "myst-reader-default.html"
DEFAULT_READING_SPEED = 200  # Words per minute

ENCODED_LINKS_TO_RAW_LINKS_MAP = {
    "%7Bstatic%7D": "{static}",
    "%7Battach%7D": "{attach}",
    "%7Bfilename%7D": "{filename}",
}

# Markdown variants supported in default files
# Update as MyST adds or removes support for formats
VALID_INPUT_FORMATS = (
    "commonmark",
    "commonmark_x",
    "gfm",
    "markdown",
    "markdown_mmd",
    "markdown_phpextra",
    "markdown_strict",
)
VALID_OUTPUT_FORMATS = ("html", "html5")
VALID_BIB_EXTENSIONS = ["json", "yaml", "bibtex", "bib"]
FILE_EXTENSIONS = ["md", "mkd", "mkdn", "mdwn", "mdown", "markdown", "Rmd"]
DEFAULT_MYST_EXECUTABLE = None
MYST_SUPPORTED_MAJOR_VERSION = 0
MYST_SUPPORTED_MINOR_VERSION = 13


class MySTReader(BaseReader):
    """Convert files written in MyST Markdown to HTML 5."""

    enabled = True
    file_extensions = FILE_EXTENSIONS
    parser_config = main.MdParserConfig()

    def read(self, source_path):
        """Parse MyST Markdown and return HTML5 markup and metadata."""
        # Get the user-defined path to the MyST executable or fall back to default
        # Open Markdown file and read content
        content = ""
        with pelican_open(source_path) as file_content:
            content = file_content

        # Retrieve HTML content and metadata
        output, metadata = self._create_html(source_path, content)

        return output, metadata

    def _create_html(self, source_path, content):
        """Create HTML5 content."""
        # Get settings set in pelicanconf.py
        default_files = self.settings.get("MYST_DEFAULT_FILES", [])
        extensions = self.settings.get("MYST_EXTENSIONS", [])

        if isinstance(extensions, list):
            self.parser_config.enable_extensions.extend(extensions)

        # Check if source content has a YAML metadata block
        self._check_yaml_metadata_block(content)

        # Find and add bibliography if citations are specified
        for bib_file in self._find_bibs(source_path):
            content += f"""

```{{bibliography}} {bib_file}
```

"""
        # Create HTML content using myst-reader-default.html template
        output = self._run_myst(content)

        # Extract table of contents, text and metadata from HTML output
        table_of_contents = True
        output, toc, myst_metadata = self._extract_contents(output, table_of_contents)

        # Replace all occurrences of %7Bstatic%7D to {static},
        # %7Battach%7D to {attach} and %7Bfilename%7D to {filename}
        # so that static links are resolvable by pelican
        for encoded_str, raw_str in ENCODED_LINKS_TO_RAW_LINKS_MAP.items():
            output = output.replace(encoded_str, raw_str)

        # Parse MyST metadata and add it to Pelican
        metadata = self._process_metadata(myst_metadata)

        if table_of_contents:
            # Create table of contents and add to metadata
            metadata["toc"] = self.process_metadata("toc", toc)

        if self.settings.get("CALCULATE_READING_TIME", []):
            # Calculate reading time and add to metadata
            metadata["reading_time"] = self.process_metadata(
                "reading_time", self._calculate_reading_time(content)
            )

        return output, metadata

    def _calculate_reading_time(self, content):
        """Calculate time taken to read content."""
        reading_speed = self.settings.get("READING_SPEED", DEFAULT_READING_SPEED)
        wordcount = count_words_in_markdown(content)

        time_unit = "minutes"
        try:
            reading_time = math.ceil(float(wordcount) / float(reading_speed))
            if reading_time == 1:
                time_unit = "minute"
            reading_time = "{} {}".format(str(reading_time), time_unit)
        except ValueError as words_per_minute_nan:
            raise ValueError(
                "READING_SPEED setting must be a number."
            ) from words_per_minute_nan

        return reading_time

    def _process_metadata(self, myst_metadata):
        """Process MyST metadata and add it to Pelican."""
        # Cycle through the metadata and process them
        metadata = {}
        for key, value in myst_metadata.items():
            key = key.lower()
            if value and isinstance(value, str):
                value = value.strip().strip('"')

            # Process the metadata
            metadata[key] = self.process_metadata(key, value)
        return metadata

    @staticmethod
    def _check_yaml_metadata_block(content):
        """Check if the source content has a YAML metadata block."""
        # Check that the given content is not empty
        if not content:
            raise Exception("Could not find metadata. File is empty.")

        # Split content into a list of lines
        content_lines = content.splitlines()

        # Check that the first line of the file starts with a YAML block
        if content_lines[0].rstrip() not in ["---"]:
            raise Exception("Could not find metadata header '---'.")

        # Find the end of the YAML block
        yaml_block_end = ""
        for line_num, line in enumerate(content_lines[1:]):
            if line.rstrip() in ["---", "..."]:
                yaml_block_end = line_num
                break

        # Check if the end of the YAML block was found
        if not yaml_block_end:
            raise Exception("Could not find end of metadata block.")

    @classmethod
    def _run_myst(cls, content):
        """Execute the given myst command and return output."""
        return main.to_html(content, config=cls.parser_config)

    @staticmethod
    def _extract_contents(html_output, table_of_contents):
        """Extract body html, table of contents and metadata from output."""
        # Extract myst metadata from html output
        myst_json_metadata, _, html_output = html_output.partition("\n")

        # Convert JSON string to dict
        myst_metadata = json.loads(myst_json_metadata)

        # Parse HTML output
        soup = bs4.BeautifulSoup(html_output, "html.parser")

        # Extract the table of contents if one was requested
        toc = ""
        if table_of_contents:
            # Find the table of contents
            toc = soup.body.find("nav", id="TOC")

            if toc:
                # Convert it to a string
                toc = str(toc)

                # Replace id=TOC with class="toc"
                toc = toc.replace('id="TOC"', 'class="toc"')

                # Remove the table of contents from the HTML output
                soup.body.find("nav", id="TOC").decompose()

        # Remove body tag around html output
        soup.body.unwrap()

        # Strip leading and trailing spaces
        html_output = str(soup).strip()

        return html_output, toc, myst_metadata

    @staticmethod
    def _find_bibs(source_path):
        """Find bibliographies recursively in the sourcepath given."""
        bib_files = []
        filename = os.path.splitext(os.path.basename(source_path))[0]
        directory_path = os.path.dirname(os.path.abspath(source_path))
        for root, _, files in os.walk(directory_path):
            for extension in VALID_BIB_EXTENSIONS:
                bib_name = ".".join([filename, extension])
                if bib_name in files:
                    bib_files.append(os.path.join(root, bib_name))
        return bib_files

    @staticmethod
    def _check_input_format(defaults):
        """Check if the input format given is a Markdown variant."""
        reader = ""
        reader_input = defaults.get("reader", "")
        from_input = defaults.get("from", "")

        # Case where no input format is specified
        if not reader_input and not from_input:
            raise ValueError("No input format specified.")

        # Case where both reader and from are specified which is not supported
        if reader_input and from_input:
            raise ValueError(
                (
                    "Specifying both from and reader is not supported."
                    " Please specify just one."
                )
            )

        if reader_input or from_input:
            if reader_input:
                reader = reader_input
            elif from_input:
                reader = from_input

            reader_prefix = reader.replace("+", "-").split("-")[0]

            # Check to see if the reader_prefix matches a valid input format
            if reader_prefix not in VALID_INPUT_FORMATS:
                raise ValueError("Input type has to be a Markdown variant.")
        return reader

    @staticmethod
    def _check_output_format(defaults):
        """Check if the output format is HTML or HTML5."""
        writer_output = defaults.get("writer", "")
        to_output = defaults.get("to", "")

        # Case where both writer and to are specified which is not supported
        if writer_output and to_output:
            raise ValueError(
                (
                    "Specifying both to and writer is not supported."
                    " Please specify just one."
                )
            )

        # Case where neither writer nor to value is set to html
        if (
            writer_output not in VALID_OUTPUT_FORMATS
            and to_output not in VALID_OUTPUT_FORMATS
        ):
            output_formats = " or ".join(VALID_OUTPUT_FORMATS)
            raise ValueError(
                "Output format type must be either {}.".format(output_formats)
            )


def add_reader(readers):
    """Add the MySTReader as the reader for all MyST Markdown files."""
    for ext in MySTReader.file_extensions:
        readers.reader_classes[ext] = MySTReader


def register():
    """Register the MySTReader."""
    signals.readers_init.connect(add_reader)
