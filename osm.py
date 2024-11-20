import logging
import ogr2osm

def setup_logger():
    ogr2osmlogger = logging.getLogger('ogr2osm')
    ogr2osmlogger.setLevel(logging.ERROR)
    ogr2osmlogger.addHandler(logging.StreamHandler())

class PolygonOnlyTranslation(ogr2osm.TranslationBase):
    def filter_geom_type(self, geom_type):
        # 只保留多边形类型 (3=多边形)
        return geom_type == 3

def convert_shp_to_osm(input_path, output_file):
    setup_logger()

    # 创建转换对象
    translation_object = PolygonOnlyTranslation()

    # 创建ogr数据源
    datasource = ogr2osm.OgrDatasource(translation_object)
    datasource.open_datasource(input_path)

    # 转换过程
    osmdata = ogr2osm.OsmData(translation_object)
    osmdata.process(datasource)

    # 输出OSM数据
    datawriter = ogr2osm.OsmDataWriter(output_file)
    osmdata.output(datawriter)

def main():
    # input_path = "/mnt/d/wang/长沙建筑数据/长沙建筑轮廓数据/长沙-20241111-v2.gpkg"
    # output_file = "长沙-v2.osm"
    # convert_shp_to_osm(input_path, output_file)

    input_path = "./base/长沙lucc-v2.gpkg"
    output_file = "./base/长沙lucc.osm"
    convert_shp_to_osm(input_path, output_file)


if __name__ == "__main__":
    main()