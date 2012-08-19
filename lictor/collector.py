import os
import sys
import simplejson
from hashlib import md5 as hasher

from django.conf import settings
from django.utils.importlib import import_module
from django.utils.datastructures import SortedDict

from lictor.models import Trace


class Tracer(object):
    frames = []

    def __init__(self):
        self.lictor_path = os.path.dirname(__file__)

    def start(self):
        """Setup the tracer"""
        sys.setprofile(self.tracer)

    def stop(self):
        sys.setprofile(None)

    def tracer(self, frame, event, arg):
        """The call handler, which receive a frame and save it to self.frames"""
        if self.lictor_path not in frame.f_code.co_filename:
            # Exclude lictor app
            self.frames.append((frame, event, arg, ))


class Graph(object):
    frames = []
    apps = []
    graph = SortedDict()

    def __init__(self, frames):
        self.frames = frames
        # Exclude some paths if it is not appear in INSTALLED_APPS
        for app in settings.INSTALLED_APPS + ('django', ):
            self.apps.append(import_module(app).__file__.rsplit('/', 1)[0])
        self.apps.remove(os.path.dirname(__file__))  # Remove lictor

    def add(self, iframe, event):
        """Add iframe to graph"""
        iframe_id = iframe.get_id()
        parent_iframe = self.find_django_parent_frame(iframe.parent)
        self.graph[iframe_id] = {
            "id": iframe_id,
            "type": iframe.get_django_type(),
            "file": iframe.get_filename(),
            "line": iframe.get_lineno(),
            "name": iframe.get_django_name(),
            "pid": parent_iframe and parent_iframe.get_id()
        }

    def find_django_parent_frame(self, iframe):
        """Binding frame-to-parent, excluding unnecessary frames"""
        while iframe:
            if iframe.get_id() in self.graph.keys():
                return iframe
            iframe = iframe.parent

    def is_available_frame(self, path=""):
        """Check frame.f_code.co_filename in INSTALLED_APPS"""
        for app_path in self.apps:
            if app_path in path:
                return True
        return False

    def build_and_save(self, session):
        """Build the graph of call stack and save result to Trace model"""
        for frame, event, arg in self.frames:
            if self.is_available_frame(path=frame.f_code.co_filename):
                iframe = FrameInspector(frame)
                self.add(iframe, event)
        for g in self.graph.values():
            print g['file']
            print
        # Trace.objects.create(
        #     session=session,
        #     json=simplejson.dumps(self.graph.values()))


class FrameInspector(object):
    """Extractor useful information from frame"""
    django_name = "FakeName"
    django_type = "FakeType"

    def __init__(self, frame):
        assert frame
        self.frame = frame
        self.inspect()

    def inspect(self):
        """Extract additional infromation from frame
        Example:
        * django type (Model, Manager, View, Url, Form, etc)
        * django name ("films.models.Film", "films.form.SomeForm", "urlpattern(^(?P<page>\d+)/$)")
        """
        if "models/manager" in self.frame.f_code.co_filename and "__get__" in self.frame.f_code.co_name:
            # models.Manager
            self.django_name = self.frame.f_locals['self'].manager.model
            self.django_type = "models.Manager"

    def get_id(self):
        """Return identificator of frame, for binging frame stack"""
        return hasher(self.get_filename() + str(self.get_lineno())).hexdigest()

    def get_filename(self):
        return self.frame.f_code.co_filename

    def get_lineno(self):
        return self.frame.f_code.co_firstlineno

    def get_django_type(self):
        return self.django_type

    def get_django_name(self):
        return self.django_name

    @property
    def parent(self):
        """Return a parent of frame"""
        try:
            return FrameInspector(self.frame.f_back)
        except:
            return None
