#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Input classes for ETL.
#
# Author: Just van den Broecke
#
from .. util import Util, etree
from .. input import Input
from .. packet import  FORMAT
from copy import deepcopy

log = Util.get_log('fileinput')

# Abstract base class for specific FileInputs
class FileInput(Input):
    # Constructor
    def __init__(self, configdict, section, produces):
        Input.__init__(self, configdict, section, produces)

        # path to file or files: can be a dir or files or even multiple, comma separated
        self.file_path = self.cfg.get('file_path')

        # The filename pattern according to Python glob.glob
        self.filename_pattern = self.cfg.get('filename_pattern', '*.[gxGX][mM][lL]')

        # Recurse into directories ?
        self.depth_search = self.cfg.get_bool('depth_search', False)

        # Create the list of files to be used as input
        self.file_list = Util.make_file_list(self.file_path, None, self.filename_pattern, self.depth_search)
        log.info("file_list=%s" % str(self.file_list))

    # Override in subclass
    def read(self, packet):
        pass

# Returns file as String
class StringFileInput(FileInput):
    # Constructor
    def __init__(self, configdict, section):
        FileInput.__init__(self, configdict, section, produces=FORMAT.string)
        self.file_list_done = []
        self.file = None
        # Optional positional formatting of content according to Python String.format()
        self.format_args = self.cfg.get_tuple('format_args')

    def read(self, packet):
        # No more files left and done with current file ?
        if not len(self.file_list) and self.file is None:
            packet.set_end_of_stream()
            log.info("EOF file list, all files done")
            return packet

        # Done with current file or first file ?
        if self.file is None:
            self.cur_file_path = self.file_list.pop(0)
            self.file = open(self.cur_file_path, 'r')
            log.info("file opened : %s" % self.cur_file_path)

        # Assume valid file content
        file_content = self.file.read()

        # Optional: string substitution based on Python String.format()
        # But you can also use StringSubstitutionFilter from filters.
        if self.format_args:
            file_content = file_content.format(*self.format_args)

        # Cleanup
        self.file.close()
        self.file = None

        log.info("file read : %s size=%d" % (self.cur_file_path, len(file_content)))

        packet.data = file_content
        return packet

# Parses XML files into etree docs
class XmlFileInput(FileInput):
    # Constructor
    def __init__(self, configdict, section):
        FileInput.__init__(self, configdict, section, produces=FORMAT.etree_doc)
        self.file_list_done = []

    def read(self, packet):
        if not len(self.file_list):
            return packet

        file_path = self.file_list.pop(0)
        # One-time read/parse only
        try:
            packet.data = etree.parse(file_path)
            log.info("file read and parsed OK : %s" % file_path)
        except Exception, e:
            log.info("file read and parsed NOT OK : %s" % file_path)

        # One-time read: we're all done
        packet.set_end_of_doc()
        if not len(self.file_list):
            log.info("all files done")
            packet.set_end_of_stream()

        self.file_list_done.append(file_path)
        return packet

# Streams lines from an XML file(s)
# NB assumed is that lines in the file have newlines !!
# TODO: make a stream-parsing lxml solution
class XmlLineStreamerFileInput(FileInput):
    # Constructor
    def __init__(self, configdict, section):
        FileInput.__init__(self, configdict, section, produces=FORMAT.xml_line_stream)
        self.file_list_done = []
        self.file = None

    def read(self, packet):
        # No more files left and done with current file ?
        if not len(self.file_list) and self.file is None:
            packet.set_end_of_stream()
            log.info("EOF file list")
            return packet

        # Done with current file or first file ?
        if self.file is None:
            self.cur_file_path = self.file_list.pop(0)
            self.file = open(self.cur_file_path, 'r')
            log.info("file opened : %s" % self.cur_file_path)

        if packet.is_end_of_stream():
            return packet

        # Assume valid line
        line = self.file.readline()

        # EOF reached ?
        if not line or line == '':
            packet.data = None

            packet.set_end_of_doc()
            log.info("EOF file")
            if self.cur_file_path is not None:
                self.file_list_done.append(self.cur_file_path)
                self.cur_file_path = None
                if not len(self.file_list):
                    # No more files left: end of stream reached
                    packet.set_end_of_stream()
                    log.info("EOF file list")

            self.file = None

            return packet

        packet.data = line.decode('utf-8')
        return packet

#  Extracts XML elements from a file, outputs each feature element in Packet
class XmlElementStreamerFileInput(FileInput):
    # Constructor
    def __init__(self, configdict, section):
        FileInput.__init__(self, configdict, section, produces=FORMAT.etree_element_stream)
        self.element_tags = self.cfg.get('element_tags').split(',')
        self.file_list_done = []
        self.context = None
        self.root = None

    def read(self, packet):
        event = None
        if self.context is None:
            if not len(self.file_list):
                # No more files left, all done
                return packet

            file_path = self.file_list.pop(0)
            file = open(file_path)
            self.context = etree.iterparse(file, events=("start", "end"))
            self.context = iter(self.context)
            event, self.root = self.context.next()

        try:
            event, elem = self.context.next()
        except StopIteration, e:
            elem = None

        if elem is None:
            self.context = None

            # Always end of doc
            packet.set_end_of_doc()

            # Maybe end of stream (all docs done)
            if not len(self.file_list):
                # No more files left: end of stream
                packet.set_end_of_stream()

            return packet

        # Filter out Namespace from the tag
        # this is the easiest way to go for now
        tag = elem.tag.split('}')
        if len(tag) == 2:
            # Namespaced tag: 2nd is tag
            tag = tag[1]
        else:
            # Non-namespaced tag: first
            tag = tag[0]

        if tag in self.element_tags:
            if event == "start":
                # TODO check if deepcopy is the right thing to do here.
                # packet.data = elem
                pass
                # self.root.remove(elem)
            elif event == "end":
                # Delete the element from the tree
                # self.root.clear()
                packet.data = elem
                self.root.remove(elem)

        return packet