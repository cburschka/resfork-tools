from collections import namedtuple
import io
import os
import struct

ResMapItem = namedtuple('ResMapItem', ['name', 'id', 'start', 'length', 'type', 'attributes'])

class ResMap:
    def __init__(self, resMap, iData, stream):
        self.map = resMap
        self.iData = iData
        self.stream = stream
        self.resources = {}

    '''Read the map data from a file.'''
    @classmethod
    def fromFile(self, stream):
        stream.seek(0)
        ranges = struct.unpack('>IIII', stream.read(16))
        iData = ranges[0], ranges[2]
        iMap = ranges[1], ranges[3]
        stream.seek(iMap[0])
        mapData = stream.read(iMap[1])
        (oTypes, oNames, nTypes,) = struct.unpack('>HHH', mapData[24:30])
        # oTypes points at the positstreamn of nTypes (ie 28); the actual type data begins 2 bytes after that.
        typeData = mapData[oTypes+2:oTypes+2+(nTypes+1)*8]
        typeRecords = [typeData[8*i:8*i+8] for i in range(nTypes+1)]
        typeList = {record[:4]: struct.unpack('>HH', record[4:]) for record in typeRecords}
        typeList = {t.decode('ascii'):(a+1, b) for (t, (a,b)) in typeList.items()}
        refData = mapData[oTypes:oNames]
        nameData = mapData[oNames:]
        refList = {}
        resMap = {}
        for typeId, (nRes, oRef) in typeList.items():
            refDataChunk = refData[oRef:oRef+12*(nRes+1)]
            refDataChunk = [struct.unpack('>HhI', refDataChunk[12*i:12*i+8]) for i in range(nRes)]
            refList[typeId] = {chunk[0]: (chunk[1], chunk[2] >> 24, chunk[2] & 0xffffff) for chunk in refDataChunk}
            for resId, (oName, attr, oData) in refList[typeId].items():
                stream.seek(iData[0] + oData)
                (lData,) = struct.unpack('>I', stream.read(4))
                if oName >= 0:
                    (lName,) = struct.unpack('>B', nameData[oName:oName+1])
                    name = nameData[oName+1:oName+1+lName].decode('macintosh')
                else:
                    name = None
                resMap[resId] = ResMapItem(id=resId, start=oData+4, length=lData, type=typeId, name=name, attributes=attr)
        return self(resMap, iData, stream)

    '''Streams have no random access and should be completely read (can also be used for regular files).'''
    @classmethod
    def fromFileStream(self, stream):
        return self.fromFile(io.BytesIO(stream.read()))

    def write(self, output=None):
        for resId in self.map:
            # Load all resource data into memory.
            self.getResource(resId)
        data = io.BytesIO()
        nameData = io.BytesIO()
        typeList = {}
        refs = {}
        refLists = {}
        # Concatenate the data and names, and reindex the item offsets.
        for resource in self.resources.values():
            item = resource.item
            oData = data.tell()
            data.write(struct.pack('>I', item.length))
            data.write(resource.data)

            if (item.name):
                iName = nameData.tell()
                name = item.name.encode('macintosh')
                nameData.write(struct.pack('>B', len(name)))
                nameData.write(name)
            else:
                iName = -1
            refs[item.id] = (item.id, iName, item.attributes << 24 | oData)

            refLists[resource.item.type] = []

        # Aggregate the resource items into ref lists.
        for resId in sorted(self.resources.keys()):
            refLists[self.resources[resId].item.type].append(refs[resId])

        # Concatenate the ref lists, and create the type list.
        typeList = []
        nTypes = len(refLists)
        refData = io.BytesIO()
        refData.write(struct.pack('>H', nTypes-1))
        refData.write(b'\0' * (8*nTypes))
        for resType, refList in refLists.items():
            typeList.append((resType.encode('macintosh'), len(refList) - 1, refData.tell()))
            print(refList)
            refData.write(b''.join(struct.pack('>HhIxxxx', *x) for x in refList))

        # Insert the type list (which comes before the refData).
        refData.seek(2)
        refData.write(b''.join(struct.pack('>4sHH', *i) for i in typeList))

        # Concatenate the map.
        resMap = io.BytesIO()
        resMap.write(28 * b'\0')
        resMap.write(refData.getvalue())
        iNames = resMap.tell()
        resMap.write(nameData.getvalue())
        resMap.seek(24)
        resMap.write(struct.pack('>HH', 28, iNames))

        data = data.getvalue()
        resMap = resMap.getvalue()

        output = output or io.BytesIO()
        output.write(16*b'\0')
        output.write(data)
        iMap = output.tell()
        output.write(resMap)

        output.seek(0)
        output.write(struct.pack('>IIII', 16, iMap, len(data), len(resMap)))

        return output

    def getResource(self, resId):
        if resId not in self.resources:
            item = self.map[resId]
            self.stream.seek(self.iData[0] + item.start)
            self.resources[resId] = Resource(item, self.stream.read(item.length))
        return self.resources[resId]

    def setResource(self, resId, resType, data, attributes=0, name=None):
        self.resources[resId] = Resource.fromStream(resId, resType, data, attributes, name)

    def extractAll(self, path):
        assert os.path.isdir(path)
        for item in self.map.values():
            if (item.name):
                filename = '{}/{}.{}.{}'.format(path, item.id, item.name, item.type.lower())
            else:
                filename = '{}/{}.{}'.format(path, item.id, item.type.lower())
            open(filename, 'wb').write(self.readData(item.id).toStream())


'''For reasons that probably made sense at the time, PICT files start with 512 bytes of nothing.'''
class PictCoder:
    def encode(data):
        return 512 * b'\0' + data

    def decode(data):
        return data[512:]

class Resource:

    coders = {
        'PICT': PictCoder
    }

    def __init__(self, item, data):
        self.item = item
        self.data = data

    @classmethod
    def fromStream(self, resId, resType, data, attributes=0, name=None):
        resType = resType.upper()
        if resType in self.coders:
            data = self.coders[resType].decode(data)
        return self(ResMapItem(id=resId, type=resType, attributes=attributes, name=name, start=0, length=len(data)), data)

    def toStream(self):
        data = self.data
        if self.type in self.coders:
            data = self.coders[self.type].encode(data)
        return data
