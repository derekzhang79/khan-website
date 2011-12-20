import request_handler
import user_util
import cgi
import re
import urllib
import logging
import layer_cache
import urllib2
import re

from api.jsonify import jsonify

from google.appengine.ext import db


import models
from models import Topic, TopicVersion, Playlist, Video, Url
        
class EditContent(request_handler.RequestHandler):

    def get(self):  
        # The following commented out code is for recreating the datastore from playlists- will remove after deploy
        # models.Topic.reindex()          
        # importSmartHistory()
        # t = models.Topic.all().filter("title = ", "Algebra").get()
        # title = t.topic_parent.topic_parent.title
        # logging.info(title)
        # self.load_demo()
        # return
        # self.load_videos()
        # self.hide_topics()
        # self.recreate_topic_list_structure()
        # return
        # version = models.TopicVersion.get_latest_version()
        # version.set_default_version()
        # return
       
        # version = models.TopicVersion.get_edit_version()
        # version.set_default_version()
        # return

        # root = Topic.get_by_id("root").make_tree()
        # root = models.Topic.get(db.Key.from_path("Topic", "root", "Topic", "math")).make_tree()
        
        version_name = self.request.get('version', 'edit')

        tree_nodes = []

        edit_version = TopicVersion.get_by_id(version_name)

        root = Topic.get_root(edit_version)
        data = root.get_visible_data()
        tree_nodes.append(data)
        
        template_values = {
            'edit_version': jsonify(edit_version),
            'tree_nodes': jsonify(tree_nodes)
            }
        logging.info(template_values)
        
        self.render_jinja2_template('topics-admin.html', template_values)
        return

    # temporary function for copying the topic structure in topics_list.py ... will remove after deploy    
    def recursive_copy_topic_list_structure(self, parent, topic_list_part):
        delete_topics = {}
        for topic_dict in topic_list_part:
            logging.info(topic_dict["name"])
            if topic_dict.has_key("playlist"):
                topic = Topic.get_by_title_and_parent(topic_dict["name"], parent)
                if topic:
                    logging.info(topic_dict["name"] + " is already created")
                else:
                    version = TopicVersion.get_edit_version()
                    root = Topic.get_root(version)
                    topic = Topic.get_by_title_and_parent(topic_dict["playlist"], root)
                    delete_topics[topic.key()] = topic
                    logging.info("copying %s to parent %s" % (topic_dict["name"], parent.title))
                    topic.copy(title = topic_dict["name"], parent = parent, standalone_title = topic.title)
            else:
                topic = Topic.get_by_title_and_parent(topic_dict["name"], parent)
                if topic:
                    logging.info(topic_dict["name"] + " is already created")
                else:
                    logging.info("adding %s to parent %s" % (topic_dict["name"], parent.title))
                    topic = Topic.insert(title = topic_dict["name"],
                                         parent = parent
                                         )

            if topic_dict.has_key("items"):
                delete_topics.update(self.recursive_copy_topic_list_structure(topic, topic_dict["items"]))

        return delete_topics       

    # temporary function for copying the topic structure in topics_list.py ... will remove after deploy  
    def recreate_topic_list_structure(self):
        import topics_list
        version = TopicVersion.get_edit_version()
        root = Topic.get_by_id("root", version)
        delete_topics = self.recursive_copy_topic_list_structure(root, topics_list.PLAYLIST_STRUCTURE)
        for topic in delete_topics.values():
            topic.delete_tree()
        version.set_default_version()

    # temporary function for marking topics not in topics_list.py as hidden - will remove after deploy
    def hide_topics(self):
        from topics_list import topics_list

        root = Topic.get_by_id("root")
        topics = Topic.all().ancestor(root).fetch(10000)
        for topic in topics:
            if topic.title not in topics_list:
                topic.hide = True
                topic.put()
            else:
                topic.hide = False
                topic.put()

    # temporary function to load videos into the topics - will remove after deploy
    def load_videos(self):
        root = Topic.get_by_id("root")
                        
        title = self.request.get('title', None)
        if title is None:
            playlist = Playlist.all().order('title').get()
        else:
            playlist = Playlist.all().filter('title = ', title).get()
        
        title = playlist.title
        
        nextplaylist = Playlist.all().filter('title >', title).order('title').get()
        if nextplaylist:
            next_title = nextplaylist.title
            next_url = "/admin/content?title="+urllib.quote(next_title)
        else:
            next_title = "FINISHED"
            next_url = None

        # next_url = None
        playlists = [playlist]
        # playlists = Playlist.all().order('title').fetch(100000)
        for i, p in enumerate(playlists):
            videos = p.get_videos()
            exercises = p.get_exercises()
            videos.extend(p.get_exercises())
            topic = Topic.insert(title = p.title,
                         parent = root,
                         description = p.description,
                         child_keys =  [video.key() for video in videos])            
                                    
            context = {
                'current_item': title,
                'next_item': next_title,
                'next_url': next_url,
            } 

            self.render_jinja2_template('update_datastore.html', context)   
            
    # temporary function to remove playlist from the fulltext index... will remove after we run it once after it gets deployed        
    def removePlaylistIndex():
        import search

        items = search.StemmedIndex.all(keys_only=True).filter("parent_kind", "Playlist").fetch(10000)
        db.delete(items)

    # temporary function to recreate the root - will remove after deploy
    def load_demo(self):
        root = Topic.insert(title = "The Root of All Knowledge",
                            description = "All concepts fit into the root of all knowledge",
                            id = "root")
        '''
        math = Topic.insert(title = "Mathematics",
                            parent = root,
                            description = "All mathematical concepts go here"
                            )
                

        arithmetic = Topic.insert(  title = "Arithmetic",
                                    parent = math,
                                    description = "Arithmetic keywords"
                                   )

        algebra = Topic.insert( title = "Algebra",
                                parent = math,
                                description = "Algebra keywords"
                                )
        '''

@layer_cache.cache(layer=layer_cache.Layers.Memcache | layer_cache.Layers.Datastore, expiration=86400)
def getSmartHistoryContent():
    request = urllib2.Request("http://smarthistory.org/khan-home.html")
    try:
        response = urllib2.urlopen(request)
        smart_history = response.read()
        smart_history = re.search(re.compile("<body>(.*)</body>", re.S), smart_history).group(1).decode("utf-8")
        smart_history.replace("script", "")
    except Exception, e:
        logging.exception("Failed fetching smarthistory video list")
        smart_history = None
        pass
    return smart_history

class ImportSmartHistory(request_handler.RequestHandler):

    # update the default and edit versions of the topic tree with smarthistory (creates a new default version if there are changes)
    def get(self):

        default = models.TopicVersion.get_default_version()
        edit = models.TopicVersion.get_edit_version()
        ImportSmartHistory.importIntoVersion(default)
        ImportSmartHistory.importIntoVersion(edit)
    
    @staticmethod
    def importIntoVersion(version):
        logging.info("comparing to version number %i" % version.number)
        topic = Topic.get_by_id("art-history", version)

        if not topic:
            parent = Topic.get_by_id("humanities---other", version)
            if not parent:
                raise Exception("Could not find the Humanities & Other topic to put art history into")
            topic = Topic.insert(title = "Art History",
                                 parent = parent,
                                 id = "art-history",
                                 standalone_title = "Art History",
                                 description = "Spontaneous conversations about works of art where the speakers are not afraid to disagree with each other or art history orthodoxy. Videos are made by <b>Dr. Beth Harris and Dr. Steven Zucker along with other contributors.</b>")  
        
        urls = topic.get_urls()
        href_to_key_dict = dict((url.url, url.key()) for url in urls)
        hrefs = [url.url for url in urls]
        content = getSmartHistoryContent()
        child_keys = []

        for link in re.finditer(re.compile('<a.*href="(.*?)"><span.*?>(.*)</span></a>', re.M), content):
            href = link.group(1)
            title = link.group(2)
            if href not in hrefs:
                logging.info("adding %i %s %s to art-history" % (i, href, title))
                url = Url(url = href,
                          title = title,
                          id = id) 
                url.put()
                child_keys.append(url.key())
            else:
                child_keys.append(href_to_key_dict[href])

        logging.info("updating child_keys")
        if topic.child_keys != child_keys:
            if version.default:
                logging.info("creating new default version")
                new_version = version.copy_version()
                new_version.description = "SmartHistory Update"
                new_version.put()
                new_topic = Topic.get_by_id("art-history", new_version)    
                new_topic.update(child_keys = child_keys)
                new_version.set_default_version()
            else:
                topic.update(child_keys = child_keys)
            logging.info("finished updating version number %i" % version.number)
        else:
            logging.info("nothing changed")

