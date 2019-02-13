#!/usr/bin/env python3
import pygit2
import os
import re
import subprocess
import shutil
from distutils.version import LooseVersion, StrictVersion

emscriptenkUrl = "https://github.com/kripken/emscripten.git"
binaryenUrl = "https://github.com/WebAssembly/binaryen.git"
llvmUrl = "https://github.com/llvm/llvm-project.git"
emsdkUrl = "https://github.com/emscripten-core/emsdk"


def checkout(sourceUrl, destinatonPath):
    os.makedirs(destinatonPath, exist_ok=True)
    repo = {}
    try: 
        repo = pygit2.Repository(destinatonPath)
    except:
        print("remote clone " + sourceUrl + " to " + destinatonPath)
        repo = pygit2.clone_repository(sourceUrl, destinatonPath)
    else:
        print("remote fetch " + sourceUrl + " to " + destinatonPath)
        repo.remotes[0].fetch()
    return repo

def tags(repo):
    regex = re.compile('^refs/tags')
    tags =  list(filter(lambda r: regex.match(r), repo.listall_references()))
    return tags

def recentEmscripteVersions(repo):
    regex = re.compile('^refs/tags/1.3')
    tags =  list(filter(lambda r: regex.match(r), repo.listall_references()))
    versons = [tag[10:] for tag in tags]
    versons.sort(reverse=True, key=lambda s: list(map(int, s.split('.'))))
    return versons

def refForVersion(version):
    if (version == "master"):
        return "refs/heads/master"
    else:
        return "refs/tags/" + version
    
def checkoutEmscripten(version):
    print("checkoutEmscripten " + version)
    emscriptenPath = "emscripten-" + version
    binaryenPath = "binaryen-" + version
    ref = refForVersion(version)

    try:
        emscripten = checkout("master/emscripten", emscriptenPath)
        emscriptenRef = ref.replace("master", "incoming") # no "master" branch in emscripten
        emscripten.checkout(emscriptenRef)
        binaryen = checkout("master/binaryen", binaryenPath)
        binaryen.checkout(ref)
    except:
        # emscripten and binaryen tags may get out of sync, for example if
        # one gets tagged with a new version before the other. Require both.
        print("emscriptenPath or binaryenPath checkout failed, deleting " + version)
        if os.path.isdir(emscriptenPath):
             shutil.rmtree(emscriptenPath) 
        if os.path.isdir(binaryenPath):
            shutil.rmtree(binaryenPath) 

    emsdkPath = "emsdk-" + version
    try:
        emsdk = checkout("master/emsdk", emsdkPath)
        emsdk.checkout("refs/heads/master")
    except:
        # delete if anything went wrong
        print("emsdk checkout failed, deleting " + version)
        shutil.rmtree(emsdkPath) 


def checkoutEmscriptens(versions):
    for version in versions:
        checkoutEmscripten(version)
        
def buildBinaryens(versions):
    for version in versions:
        print("build banaryen " + version)
        binaryenDir = "binaryen-" + version
        if not os.path.isdir(binaryenDir):
            continue

        # configure if needed
        if not os.path.isfile(binaryenDir + "/build.ninja"):
            result = subprocess.run(["cmake", "-GNinja"], cwd=binaryenDir)
        
        # build/confinue build
        result = subprocess.run(["ninja"], cwd=binaryenDir)

def installEmsdks(versions):
    for version in versions:
        print("emsdk install" + version)
        emsdkDir = "emsdk-" + version
        emsdkTag = "sdk-" + version + "-64bit"

        if not os.path.isdir(emsdkDir):
            continue

        result = subprocess.run(["./emsdk", "update-tags"], cwd=emsdkDir)
        result = subprocess.run(["./emsdk", "install", emsdkTag], cwd=emsdkDir)
        result = subprocess.run(["./emsdk", "activate", "--embedded", emsdkTag], cwd=emsdkDir)

def llvmVersionForEmscriptenVersion(emscriptenVersion):
    if emscriptenVersion == "master":
        return "master"
    if (LooseVersion(emscriptenVersion) <= LooseVersion("1.38.23")):
        return "8.0.0" # 8.0 is fine up to 1.38.23

    return "master"
    

def writeEmscriptenEnvs(versions):
    cwd = os.getcwd()
    
    for version in versions:
        
        # write env file for stockllvm builds
        fileName = "env-vanillallvm-" + version
        configFilePath =  cwd +  '/.emscripten-vanillallvm-' + version
        emscriptenPath = cwd +  '/emscripten-' + version
        llvmVersion = llvmVersionForEmscriptenVersion(version)
        
        if not os.path.isdir(emscriptenPath):
            continue # skip if the version was not checked out properly

        file = open(fileName, "w")
        file.write('export EMSDK="' + emscriptenPath  + '"\n')
        file.write('export PATH="$EMSDK:$PATH"\n')
        file.write('export LLVM="' + cwd + '/llvm-' + llvmVersion + '-build/bin"\n')
        file.write('export BINARYEN="' + cwd +  '/binaryen-' + version  + '"\n')
        file.write('export EM_CONFIG="' + configFilePath +'"\n')
        file.write('export EM_CACHE="' + cwd +  '/.emscripten-vanillallvm-cache-' + version  + '"\n')
        file.write('\n') 
        file.close()
        
        # copy emscripten config file for stockllvm builds
        shutil.copyfile(".emscripten", configFilePath)
        
        # write env file for emsdk builds
        fileName = "env-emsdk-{}".format(version)
        file = open(fileName, "w")
        file.write("source emsdk-{}/emsdk_env.sh\n".format(version))
        file.write('\n') 
        file.close()

#refs/tags/

def llvmVersions(repo):
    versions = tags(repo)
    versions = [tag.split('-', 1)[1] for tag in versions]           # refs/tags/llvmorg-3.9.0-rc1 -> 3.9.0
    #versons = list(filter(lambda r: "0.0" in r, versions))   # skip patch releases ## would rather use x.0.1 than x.0.0
    #versons = list(set(versions))
    
    versions.sort(reverse=True, key=lambda s: list(map(int, s.split('-')[0].split('.'))))
    #versions = list(filter(lambda r: "-rc" not in r, versions)) # skip release candidates

    # pick the most recent major vesrsions (7.0.2, 6.0.1, etc)
    majorVersionsNumbers = set()
    majorVersions = []
    for version in versions:
        majorVersionNumber = version.split(".")[0]
        if majorVersionNumber in majorVersionsNumbers:
            continue
        
        majorVersionsNumbers.add(majorVersionNumber)
        majorVersions.append(version)
    
    return majorVersions

def llvmDirFromVersion(version):
    return version.split("-")[0] # remove any '-rc'

def checkoutLlvm(version):
    print(version)
    print(llvmDirFromVersion(version))
    llvm = checkout("master/llvm", "llvm-" + llvmDirFromVersion(version))
    if version == "master":
        llvm.checkout("refs/heads/master")
    else:
        llvm.checkout("refs/tags/llvmorg-" + version)

def checkoutLlvms(versions):
    for version in versions:
        checkoutLlvm(version)

def buildLlvm(version):
    sourceDir = "llvm-" + llvmDirFromVersion(version)
    buildDir = sourceDir + "-build"
    os.makedirs(buildDir, exist_ok=True)

    cmakeCommand = [
        "cmake", "-GNinja",
        "../" + sourceDir + "/llvm",
        '-DLLVM_ENABLE_PROJECTS=clang;libcxx;libcxxabi;lld',
        '-DCMAKE_BUILD_TYPE=Release',
        '-DLLVM_TARGETS_TO_BUILD=WebAssembly',
        '-DLLVM_EXPERIMENTAL_TARGETS_TO_BUILD=WebAssembly',
    ]

    # configure if needed
    if not os.path.isfile(buildDir + "/build.ninja"):
        result = subprocess.run(cmakeCommand, cwd=binaryenDir)
    
    result = subprocess.run(["ninja"], cwd=buildDir)

def buildLlvms(versions):
    for version in versions:
        buildLlvm(version)
        
def setupEmscripten():
    emscripten = checkout(emscriptenkUrl, "master/emscripten")
    binaryen = checkout(binaryenUrl, "master/binaryen")
    emsdk = checkout(emsdkUrl, "master/emsdk")

    versions = recentEmscripteVersions(emscripten)
    recentVersions = versions[:12] + ["master"]
    checkoutEmscriptens(recentVersions)
    writeEmscriptenEnvs(recentVersions)
    buildBinaryens(recentVersions)
    installEmsdks(recentVersions)

def setupLlvm():
    llvm = checkout(llvmUrl, "master/llvm")
    versions = llvmVersions(llvm)
    recentVersions = versions[:1] + ["master"]
    print(recentVersions)
    checkoutLlvms(recentVersions)
    buildLlvms(recentVersions)

setupEmscripten()
setupLlvm()

# print(versions)

