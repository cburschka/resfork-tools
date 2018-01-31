from collections import namedtuple
import struct

ResMapItem = namedtuple('ResMapItem', ['name', 'id', 'start', 'length', 'type'])

class ResMap:
    def __init__(self, io):
        self.io = io
        io.seek(0)
        ranges = struct.unpack('>IIII', io.read(16))
        self.iData = ranges[0], ranges[2]
        self.iMap = ranges[1], ranges[3]
        
        self.map = self.readMap()

    '''Read the map data from the file.'''
    def readMap(self):
        self.io.seek(self.iMap[0])
        mapData = self.io.read(self.iMap[1])
        (oTypes, oNames, nTypes,) = struct.unpack('>HHH', mapData[24:30])
        # oTypes points at the position of nTypes (ie 28); the actual type data begins 2 bytes after that.
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
            refList[typeId] = {chunk[0]: (chunk[1], chunk[2] & 0xffffff) for chunk in refDataChunk}
            for resId, (oName, oData) in refList[typeId].items():
                self.io.seek(self.iData[0] + oData)
                (lData,) = struct.unpack('>I', self.io.read(4))
                if oName >= 0:
                    (lName,) = struct.unpack('>B', nameData[oName:oName+1])
                    # 
                    name = nameData[oName+1:oName+1+lName].decode('macintosh')
                else:
                    name = None
                resMap[resId] = ResMapItem(id=resId, start=oData+4, length=lData, type=typeId, name=name)
        return resMap

    def __getitem__(self, resId):
        return self.map[resId]     

    def readData(self, resId):
        item = self[resId]
        self.io.seek(self.iData[0] + item.start)
        return ResourceData(item.type, self.io.read(item.length))

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

class ResourceData:

    coders = {
        'PICT': PictCoder
    }

    def __init__(self, resType, data):
        self.type = resType.upper()
        self.data = data

    @classmethod
    def fromStream(resType, data):
        resType = resType.upper()
        if resType in self.coders:
            data = self.coders[resType].decode(data)
        return self(resType, data)

    def toStream(self):
        data = self.data
        if self.type in self.coders:
            data = self.coders[self.type].encode(data)
        return data
