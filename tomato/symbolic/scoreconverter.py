from musicxmlconverter import symbtr2musicxml
from musicxml2lilypond import scoreconverter as musicxml2lilypond
from symbtrdataextractor.reader.symbtr import SymbTrReader
from symbtrextras.scoreextras import ScoreExtras
from symbtrdataextractor.metadata.musicbrainz import MusicBrainzMetadata
from ..io import IO
from six.moves import configparser
from ..bincaller import BinCaller
import os
import subprocess
import tempfile
import re
import musicbrainzngs

_bin_caller = BinCaller()


class ScoreConverter(object):
    _mb_meta_getter = MusicBrainzMetadata()
    _xml2ly_converter = musicxml2lilypond.ScoreConverter()

    @classmethod
    def convert(cls, symtr_txt_filename, symbtr_mu2_filename, symbtr_name=None,
                mbid=None, render_metadata=True, svg_paper_size='a4',
                xml_out=None, ly_out=None, svg_out=None):
        xml_output = cls.txt_mu2_to_musicxml(
            symtr_txt_filename, symbtr_mu2_filename, xml_out=xml_out,
            symbtr_name=symbtr_name, mbid=mbid)

        ly_output, ly_txt_mapping = cls.musicxml_to_lilypond(
            xml_in=xml_output, ly_out=ly_out, render_metadata=render_metadata)

        svg_output = cls.lilypond_to_svg(
            ly_output, svg_out=svg_out, paper_size=svg_paper_size,
            ly_txt_mapping=ly_txt_mapping)

        return xml_output, ly_output, svg_output, ly_txt_mapping

    @classmethod
    def txt_mu2_to_musicxml(cls, txt_file, mu2_file, xml_out=None,
                            symbtr_name=None, mbid=None):
        if symbtr_name is None:
            symbtr_name = SymbTrReader.get_symbtr_name_from_filepath(txt_file)

        mbid_url = cls._get_mbid_url(mbid, symbtr_name)

        piece = symbtr2musicxml.SymbTrScore(
            txt_file, mu2_file, symbtrname=symbtr_name, mbid_url=mbid_url)

        xmlstr = piece.convertsymbtr2xml()  # outputs the xml score as string
        if xml_out is None:   # return string
            return xmlstr
        else:
            piece.writexml(xml_out)  # save to filename
            return xml_out  # return filename

    @classmethod
    def _get_mbid_url(cls, mbid, symbtr_name):
        if mbid is None:
            try:
                mbid_url = ScoreExtras.get_mbids(symbtr_name)[0]
            except IndexError:
                mbid_url = None
        else:
            try:  # find if it is a work or recording mbid
                meta = cls._mb_meta_getter.crawl_musicbrainz(mbid)
                mbid_url = meta['url']
            except (musicbrainzngs.NetworkError, musicbrainzngs.ResponseError):
                mbid_url = mbid
        return mbid_url

    @classmethod
    def musicxml_to_lilypond(cls, xml_in, ly_out=None, render_metadata=True):
        ly_stream, mapping_tuple = cls._xml2ly_converter.convert(
            xml_in, ly_out=ly_out, render_metadata=render_metadata)

        # mappings
        ly_txt_mapping = {}
        for s, c, r in mapping_tuple:
            ly_txt_mapping[r] = s

        if ly_out is None:
            return ly_stream, ly_txt_mapping
        else:  # ly_stream is already saved to the user-specified file
            return ly_out, ly_txt_mapping

    @classmethod
    def lilypond_to_svg(cls, ly_in, svg_out=None, paper_size='a4',
                        ly_txt_mapping=None):
        if os.path.isfile(ly_in):
            temp_in_file = ly_in
        else:
            # create the temporary input to write the lilypond file
            temp_in_file = IO.create_temp_file('.ly', ly_in.encode('utf-8'))

        # LilyPond inputs many pages of svg, create a folder for them
        tmp_dir = tempfile.mkdtemp()

        # call lilypond ...
        lilypond_path = cls._get_lilypond_bin_path()
        callstr = u'{0:s} -dpaper-size=\\"{1:s}\\" -dbackend=svg ' \
                  u'-o {2:s} {3:s}'.format(lilypond_path, paper_size, tmp_dir,
                                           temp_in_file)

        subprocess.call(callstr, shell=True)

        if not os.path.isfile(ly_in):  # str input, temporary file was created
            IO.remove_temp_files(temp_in_file)

        # Lilypond saves the svg into pages, i.e. different files with
        # consequent naming in the tmp_dir
        svg_pages = cls._get_svg_pages(tmp_dir, ly_txt_mapping)

        if svg_out is None:  # return string
            return svg_pages
        else:
            fnames = cls._write_svgs(svg_pages, svg_out, ly_in)
            return fnames  # output path

    @classmethod
    def _get_svg_pages(cls, tmp_dir, ly_txt_mapping):
        # get the files
        svg_files = cls._get_svg_page_files(tmp_dir)

        if not svg_files:
            raise RuntimeError("No svg files are generated. Is LilyPond "
                               "installed")
        # Lilypond labels each vector in the svg with the row, starting and
        # final index of the element in lilypond, for example:
        #  xlink:href="textedit:///<file>:<ly_row>:<ly_start_col>:<ly_end_col>"
        # compile this pattern as a regular expression
        ptr = re.compile(r'<a style="(.*)" xlink:href="textedit:///.*'
                         r':([0-9]+):([0-9]+):([0-9]+)">$\n<path', re.MULTILINE)

        def replace_svg_index(x):
            """
            Regular expression replacement rule:
                We don't need the redundant <file> in the pattern. Also the
            lilypond produced has a single note each line so <ly_start_col>
            and <ly_end_col>. We remove these.
                If the symbtr mapping is given, we replace the <ly_row> with
            the mapped SymbTr-txt index
            :param x: regular expression pattern
            :return: replaced pattern
            """
            if ly_txt_mapping:
                ly_idx = int(x.group(2))
                try:  # replace the ly id embedded in the svg element with
                    # symbtr-txt id
                    symbtr_idx = ly_txt_mapping[ly_idx]
                    return r'<a id="note-{0:d}"><path'.format(symbtr_idx)
                except KeyError:
                    # the vector is not a note, hence it is not in the mapping
                    return r'<a>'
            else:
                return r'<a id="{0:s}">'.format

        # get the svg strings and organize the labels inside with regular
        # expression substitution according to the pattern and rule defined
        # above
        svg_pages = []
        for svg_file in svg_files:
            with open(svg_file, 'r') as f:  # get the organized svg string
                svg_pages.append(ptr.sub(replace_svg_index, f.read()))
            os.remove(svg_file)  # remove temporary file
        os.rmdir(tmp_dir)

        return svg_pages

    @staticmethod
    def _write_svgs(svg_pages, svg_out, ly_in):
        """
        Writes the svgs saved to many pages to according to the output.
        - If svg_out is a folder:
            The name of the svg outputs are derived from ly_in, if ly_in is
            a file else the output is saved with string "score" prepended to
            the output files
        - If the svg_out is a string
            svg_out defines the path and the naming template (e.g. "path/name")
        If there is a single page, the output is saved to the template string
        obtained in the procedure above appended with the .svg extension.
        If there are multiple pages, each page is save in the same namig
        converntion with LilyPond, e.g. [template_name]-page-X.svg.
        """
        if os.path.isdir(svg_out):  # directory supplied, write svgs here
            if os.path.isfile(ly_in):  # get the name from the .ly file input
                template = os.path.splitext(os.path.basename(ly_in))[0]
            else:  # lilypond was given as a string, prepend "score"
                template = 'score'
            template = os.path.join(svg_out, template)
        else:  # name template is given directly
            template = svg_out

        fnames = []
        for pp, page in enumerate(svg_pages):
            if len(svg_pages) == 1:  # if there is a single page don't
                # append "-page-1"
                fnames.append(u'{0:s}.svg'.format(template))
            else:  # append page numbers
                fnames.append(u'{0:s}-page-{1:d}.svg'.format(template, pp + 1))
            with open(fnames[-1], 'w') as f:
                f.write(page)
        return fnames  # return filepaths

    @staticmethod
    def _get_svg_page_files(tmp_dir):
        # get all files in the directory
        svg_files = [os.path.join(tmp_dir, svg_file)
                     for svg_file in os.listdir(tmp_dir)]

        # remove anything that is not a file ending with .svg
        svg_files = filter(os.path.isfile, svg_files)
        svg_files = [s for s in svg_files if s.endswith('.svg')]

        # sort the pages according to creation time
        svg_files.sort(key=lambda x: os.path.getmtime(x))
        return svg_files

    @staticmethod
    def _get_lilypond_bin_path():
        config = configparser.SafeConfigParser()
        lily_cfgfile = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    '..', 'config', 'lilypond.cfg')
        config.read(lily_cfgfile)

        # check custom
        lilypath = config.get('custom', 'custom')

        # linux path might be given with $HOME; convert it to the real path
        lilypath = lilypath.replace('$HOME', os.path.expanduser('~'))

        if lilypath:
            assert os.path.exists(lilypath), \
                'The lilypond path is not found. Please correct the custom ' \
                'section in "tomato/config/lilypond.cfg".'
        else:  # defaults
            lilypath = config.defaults()[_bin_caller.sys_os]

            assert (os.path.exists(lilypath) or
                    _bin_caller.call('which {0:s}'.format(lilypath))[0]), \
                'The lilypond path is not found. Please correct the custom ' \
                'section in "tomato/config/lilypond.cfg".'

        return lilypath