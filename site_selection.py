# 导入所需的库
import random
from shapely.geometry import Point, Polygon, LineString, MultiLineString, MultiPolygon
from math import cos, sin, pi
from enum import Enum
import os
import osmium
import geopandas as gpd
from pathlib import Path

class ShapeType(Enum):
    PENTAGON = 'pentagon' 
    CIRCLE = 'circle'

class OSMHandler(osmium.SimpleHandler):
    def __init__(self):
        super(OSMHandler, self).__init__()
        self.buildings = []
        self.roads = []
        self.parks = []
        self.water = []
        self.nodes = {}
        self.ways = {}

    def node(self, n):
        self.nodes[n.id] = (n.lon, n.lat)

    def way(self, w):
        points = []
        try:
            for n in w.nodes:
                if n.ref in self.nodes:
                    points.append(self.nodes[n.ref])
        except osmium.InvalidLocationError:
            return

        if len(points) < 2:
            return

        try:
            # Store the way for potential relation use
            self.ways[w.id] = w

            if 'building' in w.tags:
                if len(points) >= 3:
                    if points[0] == points[-1]:
                        self.buildings.append(Polygon(points))
                    else:
                        points.append(points[0])
                        self.buildings.append(Polygon(points))
            elif 'highway' in w.tags:
                self.roads.append(LineString(points))
            elif w.tags.get('leisure') == 'park':
                if len(points) >= 3:
                    if points[0] == points[-1]:
                        self.parks.append(Polygon(points))
                    else:
                        points.append(points[0])
                        self.parks.append(Polygon(points))
            elif w.tags.get('natural') == 'water':
                if len(points) >= 3:
                    if points[0] == points[-1]:
                        self.water.append(Polygon(points))
                    else:
                        points.append(points[0])
                        self.water.append(Polygon(points))
        except:
            pass

    def relation(self, r):
        multipolygon_parts = []
        multilinestring_parts = []
        for member in r.members:
            if member.type == 'w' and member.ref in self.ways:
                points = []
                try:
                    for n in self.ways[member.ref].nodes:
                        if n.ref in self.nodes:
                            points.append(self.nodes[n.ref])
                except osmium.InvalidLocationError:
                    continue

                if len(points) >= 2:
                    if member.role == 'outer' or member.role == 'inner':
                        if points[0] != points[-1]:
                            points.append(points[0])
                        multipolygon_parts.append(Polygon(points))
                    else:
                        multilinestring_parts.append(LineString(points))

        if len(multipolygon_parts) > 0:
            try:
                multipoly = MultiPolygon(multipolygon_parts)
                if 'building' in r.tags:
                    self.buildings.append(multipoly)
                elif r.tags.get('leisure') == 'park':
                    self.parks.append(multipoly)
                elif r.tags.get('natural') == 'water':
                    self.water.append(multipoly)
            except:
                pass

        if len(multilinestring_parts) > 0:
            try:
                multiline = MultiLineString(multilinestring_parts)
                if 'highway' in r.tags:
                    self.roads.append(multiline)
            except:
                pass

class GeoDataManager:
    def __init__(self, osm_file="长沙.osm", output_dir="osm_data"):
        # 初始化地理数据管理器
        self.osm_file = Path(osm_file)
        if not self.osm_file.exists():
            raise FileNotFoundError(f"OSM file not found: {osm_file}")

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.data = self._load_data()

    def _load_data(self):
        try:
            # 尝试从本地读取数据
            if self._check_local_files():
                return self._read_local_files()

            # 如果本地文件不存在，从OSM文件读取并保存
            return self._read_osm_and_save()

        except Exception as e:
            print(f"Error loading data: {e}")
            return {
                'buildings': gpd.GeoDataFrame(),
                'roads': gpd.GeoDataFrame(), 
                'parks': gpd.GeoDataFrame(),
                'water': gpd.GeoDataFrame()
            }

    def _check_local_files(self):
        files = ['buildings.gpkg', 'roads.gpkg', 'parks.gpkg', 'water.gpkg']
        return all((self.output_dir / f).exists() for f in files)

    def _read_local_files(self):
        return {
            'buildings': gpd.read_file(self.output_dir / 'buildings.gpkg'),
            'roads': gpd.read_file(self.output_dir / 'roads.gpkg'),
            'parks': gpd.read_file(self.output_dir / 'parks.gpkg'),
            'water': gpd.read_file(self.output_dir / 'water.gpkg')
        }

    def _read_osm_and_save(self):
        handler = OSMHandler()
        handler.apply_file(str(self.osm_file))

        buildings = gpd.GeoDataFrame(geometry=handler.buildings, crs='EPSG:4326')
        roads = gpd.GeoDataFrame(geometry=handler.roads, crs='EPSG:4326')
        parks = gpd.GeoDataFrame(geometry=handler.parks, crs='EPSG:4326')
        water = gpd.GeoDataFrame(geometry=handler.water, crs='EPSG:4326')

        # 转换坐标系
        buildings = buildings.to_crs('EPSG:32650')
        roads = roads.to_crs('EPSG:32650')
        parks = parks.to_crs('EPSG:32650')
        water = water.to_crs('EPSG:32650')

        # 保存到本地
        buildings.to_file(self.output_dir / 'buildings.gpkg', driver='GPKG')
        roads.to_file(self.output_dir / 'roads.gpkg', driver='GPKG')
        parks.to_file(self.output_dir / 'parks.gpkg', driver='GPKG')
        water.to_file(self.output_dir / 'water.gpkg', driver='GPKG')

        return {
            'buildings': buildings,
            'roads': roads,
            'parks': parks,
            'water': water
        }

    def create_buffer(self, data, buffer_size):
        # 创建缓冲区
        return data.geometry.buffer(buffer_size)

class ShapeGenerator:
    def __init__(self, min_dist=200, max_dist=550):
        # 初始化形状生成器,设置最小和最大距离
        self.min_dist = min_dist
        self.max_dist = max_dist

    def _create_point(self, current_point):
        # 根据当前点生成新的随机点
        angle = random.uniform(0, 360)
        distance = random.uniform(self.min_dist, self.max_dist)
        dx = distance * cos(angle * pi / 180)
        dy = distance * sin(angle * pi / 180)
        return Point(current_point.x + dx, current_point.y + dy)

    def _create_polygon(self, center, distance, vertices, rotation=0):
        # 创建多边形
        points = []
        for i in range(vertices):
            angle = 2 * pi * i / vertices + rotation
            x = center.x + distance * cos(angle)
            y = center.y + distance * sin(angle)
            points.append((x, y))
        # Close the ring by adding the first point again
        points.append(points[0])
        return Polygon(points)

    def generate_shapes(self, current_point, shape_type=ShapeType.PENTAGON):
            # 生成形状(五边形或圆形)
            distance = random.uniform(self.min_dist, self.max_dist)
            shapes = []

            for i in range(3):
                if shape_type == ShapeType.PENTAGON:
                    shapes.append(self._create_polygon(current_point, distance, 5, int(i * 2 * pi / 3)))
                elif shape_type == ShapeType.CIRCLE:
                    center_x = current_point.x + distance * cos(i * 2 * pi / 3)
                    center_y = current_point.y + distance * sin(i * 2 * pi / 3)
                    circle_center = Point(center_x, center_y)
                    shapes.append(self._create_polygon(circle_center, distance, 32))

            return shapes

class SiteSelection:
    def __init__(self, buildings_gdf, parks_gdf, water_buffer, road_buffer):
        # 初始化选址验证器
        self.buildings_gdf = buildings_gdf
        self.parks_gdf = parks_gdf
        self.water_buffer = water_buffer
        self.road_buffer = road_buffer

    def is_valid_point(self, point, generated_polygons):
        # 验证点的有效性
        in_building = self.buildings_gdf.geometry.contains(point).any()
        in_park = self.parks_gdf.geometry.contains(point).any()
        not_in_water = not any(buffer.contains(point) for buffer in self.water_buffer)
        not_in_road = not any(buffer.contains(point) for buffer in self.road_buffer)
        not_in_existing = not any(polygon.contains(point) for polygon in generated_polygons)

        return (in_building or in_park) and not_in_water and not_in_road and not_in_existing

def main():
    # 主函数
    geo_manager = GeoDataManager("osm_data/长沙.osm")
    data = geo_manager.data

    # for o in osmium.FileProcessor('osm_data/长沙.osm', osmium.osm.NODE):
    #     print(f"Node {o.id}: lat = {o.lat} lon = {o.lon}")

    # # 创建水域和道路的缓冲区
    # water_buffer = geo_manager.create_buffer(data['water'], 30)
    # road_buffer = geo_manager.create_buffer(data['roads'], 50)
    # print("水域和道路缓冲区生成完成")

    # validator = SiteSelection(data['buildings'], data['parks'], water_buffer, road_buffer)
    # shape_gen = ShapeGenerator()

    # # 设置起始点并转换到UTM投影
    # start_point = Point(112.9793, 28.1989)
    # generated_polygons = []

    # # 生成有效点和形状
    # while True:
    #     new_point = shape_gen._create_point(start_point)
    #     if validator.is_valid_point(new_point, generated_polygons):
    #         shapes = shape_gen.generate_shapes(new_point, ShapeType.PENTAGON)
    #         generated_polygons.extend(shapes)
    #         print(f"生成的下一个点坐标: {new_point.x}, {new_point.y}")
    #         break

if __name__ == "__main__":
    main()