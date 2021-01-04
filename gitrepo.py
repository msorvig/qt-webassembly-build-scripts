import pygit2
import os
import re

def fetchOrClone(sourceUrl, destinatonPath):
    os.makedirs(destinatonPath, exist_ok=True)
    repo = {}
    try: 
        repo = pygit2.Repository(destinatonPath)
    except:
        print("remote clone " + sourceUrl + " to " + destinatonPath)
        repo = pygit2.clone_repository(sourceUrl, destinatonPath)
    else:
        print("remote fetch " + sourceUrl + " to " + destinatonPath)
        # ### this does not seem to fetch new tags (?)
        repo.remotes["origin"].fetch()

    return repo

def tags(repo):
    regex = re.compile('^refs/tags')
    tags =  list(filter(lambda r: regex.match(r), repo.listall_references()))
    return tags
