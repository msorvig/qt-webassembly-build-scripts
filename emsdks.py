#!/usr/bin/env python3
import pygit2
import os
import re
import subprocess
import shutil
from distutils.version import LooseVersion, StrictVersion
import gitrepo
import argparse
import threading
import copy 

emscriptenkUrl = "https://github.com/kripken/emscripten.git"
binaryenUrl = "https://github.com/WebAssembly/binaryen.git"
llvmUrl = "https://github.com/llvm/llvm-project.git"
emsdkUrl = "https://github.com/emscripten-core/emsdk"
emsdkMaster = "emsdk"
dryRun = False


# historical versions, used by Qt. From https://doc.qt.io/qt-5/wasm.html
legacyQtEmsdkVersions = ["1.38.16", "1.38.27", "1.38.30"]


def parallel(*args):
    threads = set()
    for x in args:
        thread = threading.Thread(target = x)
        thread.deamon = False
        threads.add(thread)
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

def parallelMap(list, fn):
    threads = set()
    for x in list:
        thread = threading.Thread(target = lambda y=x: fn(y))
        thread.deamon = False
        threads.add(thread)
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

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
        emscripten = gitrepo.fetchOrClone("master/emscripten", emscriptenPath)
        emscriptenRef = ref.replace("master", "incoming") # no "master" branch in emscripten
        emscripten.checkout(emscriptenRef)
        binaryen = gitrepo.fetchOrClone("master/binaryen", binaryenPath)
        binaryen.checkout(ref)
    except:
        # emscripten and binaryen tags may get out of sync, for example if
        # one gets tagged with a new version before the other. Require both.
        print("emscriptenPath or binaryenPath checkout failed, deleting " + version)
        if os.path.isdir(emscriptenPath):
             shutil.rmtree(emscriptenPath) 
        if os.path.isdir(binaryenPath):
            shutil.rmtree(binaryenPath) 

    checkoutEmsdk(version) ### preserving historical behavior - remoe?

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

def checkoutEmsdk(version):
    emsdkDir = "emsdk-" + version
    print(f"checkout emsdk to {emsdkDir}")
    if dryRun:
        return
    try:
        emsdk = gitrepo.fetchOrClone(emsdkMaster, emsdkDir)
        emsdk.checkout("refs/heads/master")
    except:
        # delete if anything went wrong
        print("emsdk checkout failed, deleting " + version)
        shutil.rmtree(emsdkDir)

def checkoutEmsdks(versions):
    for version in versions:
        checkoutEmsdk(version)

def installEmsdk(version):
    emsdkDir = "emsdk-" + version
    emsdkTag = version
    print(f"emsdk install version {version} in dir {emsdkDir}, using tag {emsdkTag}")
    if dryRun:
        return

    if not os.path.isdir(emsdkDir):
        print("emsdkDir not found")
        return

    result = subprocess.run(["./emsdk", "update-tags"], cwd=emsdkDir)
    result = subprocess.run(["./emsdk", "install", emsdkTag], cwd=emsdkDir)
    if result.returncode != 0:
        emsdkTag = "sdk-fastcomp-" + version + "-64bit"
        print(f"installing sdk version {version} failed, trying with tag {emsdkTag}")
        result = subprocess.run(["./emsdk", "install", emsdkTag], cwd=emsdkDir)
        
        if result.returncode != 0:
            print(f"installing sdk version {version} failed. giving up.")
            shutil.rmtree(emsdkDir) 
            return
    
    result = subprocess.run(["./emsdk", "activate", "--embedded", emsdkTag], cwd=emsdkDir)

def installEmsdks(versions):
    for version in versions:
        installEmsdk(version)

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
        writeEmsdkEnv(version)

def writeEmsdkEnvs(versions):
    for version in versions:
        writeEmsdkEnv(version)

def writeEmsdkEnv(version):
    cwd = os.getcwd()
    fileName = f"env-emsdk-{version}"
    file = open(fileName, "w")
    file.write(f"source {cwd}/emsdk-{version}/emsdk_env.sh\n")
    file.write('\n') 
    file.close()

#refs/tags/

def llvmVersions(repo):
    versions = tags(repo)
    versions = [tag.split('-', 1)[1] for tag in versions]           # refs/tags/llvmorg-3.9.0-rc1 -> 3.9.0
    #versions = list(filter(lambda r: "0.0" in r, versions))   # skip patch releases ## would rather use x.0.1 than x.0.0
    #versions = list(set(versions))
    
    versions.sort(reverse=True, key=lambda s: list(map(int, s.split('-')[0].split('.'))))
    #versions = list(filter(lambda r: "-rc" not in r, versions)) # skip release candidates

    # pick the most recent major vesions (7.0.2, 6.0.1, etc)
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
    llvm = gitrepo.fetchOrClone("master/llvm", "llvm-" + llvmDirFromVersion(version))
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
    
    emscripten = gitrepo.fetchOrClone(emscriptenkUrl, "master/emscripten")
    binaryen = gitrepo.fetchOrClone(binaryenUrl, "master/binaryen")
    emsdk = gitrepo.fetchOrClone(emsdkUrl, emsdkMaster)
    
    # emscripten version structure looks like
    #   1.38.41
    #   1.38.41-upstream
    # specal versions (compile from source)
    #   sdk-incoming-64bit
    #   sdk-master-64bit 

    recentVersionCount = 2
    versions = recentEmscripteVersions(emscripten)
    recentVersions = versions[:recentVersionCount]
    expandedVersionList = recentVersions
    #expandedVersionList ?=  [version + "-upstream" for version in recentVersions];
    # expandedVersionList += ["sdk-incoming-64bit"]
    print(expandedVersionList)
    exit(0)

    # install emsdk versions
    checkoutEmsdks(expandedVersionList)
    installEmsdks(expandedVersionList)
    writeEmsdkEnvs(expandedVersionList)
    
    # check out from surce
    #checkoutEmscriptens(recentVersions)
    #buildBinaryens(recentVersions)
    
    #writeEmscriptenEnvs(recentVersions)

def setupLlvm():
    llvm = gitrepo.fetchOrClone(llvmUrl, "master/llvm")
    versions = llvmVersions(llvm)
    recentVersions = versions[:1] + ["master"]
    print(recentVersions)
    checkoutLlvms(recentVersions)
    buildLlvms(recentVersions)
    
def setupEmsdkMaster():
    emsdk = gitrepo.fetchOrClone(emsdkUrl, emsdkMaster)
    return emsdk

#setupEmscripten()
#setupLlvm()
# print(versions)

def getEmscriptenSdkVersions():
    setupEmsdkMaster();
    result = subprocess.run(["./emsdk list --old"], cwd=emsdkMaster, stdout=subprocess.PIPE, shell=True)
    lines = result.stdout.decode("utf-8").splitlines()
    
    # Grab recent versions automatically.
    autoversions = []
    for line in lines:
        candidate = line.strip()
        
        # for now, 1.39.*  and 2 (and not fastcomp)
        if (candidate.startswith("1.39.") or candidate.startswith("2.")) and not "fastcomp" in candidate:
            autoversions.append(candidate)

    
    allversions = legacyQtEmsdkVersions + autoversions
    allversions = list(set(allversions))
    allversions.sort()
    return allversions

def printEmsdkVersions():
    versions = getEmscriptenSdkVersions()
    
    print(versions)


def installEmsdkVersion(version):
    print(f"\nInstalling {version}")
    checkoutEmsdk(version)
    installEmsdk(version)
    writeEmsdkEnv(version)


def installEmsdkVersions(versions):
    print(versions)
    parallelMap(versions, installEmsdkVersion)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='emsdk installer')
    parser.add_argument("command", help="command: <versions> <install> <install-master>")
    parser.add_argument("--dryrun", dest='dryRun', action='store_true', help="Dry run (do nothing)")
    parser.set_defaults(dryRun=False)

    args = parser.parse_args()
    dryRun = args.dryRun
    
    print(f"Command: {args.command}")
    
    if args.command == "versions":
        printEmsdkVersions()
    if args.command == "install":
        installEmsdkVersions(getEmscriptenSdkVersions())
    if args.command == "install-master":
        setupEmsdkMaster()

