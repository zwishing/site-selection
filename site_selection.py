# 导入所需的库
import random
from shapely.geometry import Point, Polygon
from math import cos, sin, pi  
from enum import Enum
import geopandas as gpd
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple

# 配置参数
@dataclass
class Config:
    """程序运行的配置参数"""
    MIN_DISTANCE: float = 220  # 最小距离
    MAX_DISTANCE: float = 550  # 最大距离 
    WATER_BUFFER: float = 40   # 水域缓冲区大小
    ROAD_BUFFER: float = 60    # 道路缓冲区大小
    MAX_ATTEMPTS: int = 100000  # 最大尝试次数
    TARGET_POINTS: int = 500    # 目标生成点数量
    START_POINT: Tuple[float, float] = (112.998061, 28.17708)  # 起始点坐标
    OUTPUT_FILE: str = "generated_points-1000-v4.gpkg"  # 输出文件名
    CIRCLES_FILE: str = "generated_circles-1000-v4.gpkg" # 输出圆形文件名

class ShapeType(Enum):
    """形状类型枚举"""
    PENTAGON = 'pentagon'
    CIRCLE = 'circle'

class GeoDataManager:
    """地理数据管理类"""
    def __init__(self, gpkg_file: str = "osm_data/长沙.gpkg"):
        self.gpkg_file = Path(gpkg_file)
        if not self.gpkg_file.exists():
            raise FileNotFoundError(f"GPKG文件未找到: {gpkg_file}")
        self.data = self._load_data()

    def _load_data(self) -> dict:
        """加载地理数据"""
        try:
            data = {
                'buildings': self._read_layer('multipolygons', "building IS NOT NULL"),
                'roads': self._read_layer('lines', "highway IS NOT NULL"), 
                'parks': self._read_layer('multipolygons', "leisure='park'"),
                'water': self._read_layer('multipolygons', "natural='water'")
            }
            return self._transform_crs(data)
        except Exception as e:
            print(f"数据加载错误: {e}")
            return self._create_empty_data()

    def _read_layer(self, layer: str, where_clause: str) -> gpd.GeoDataFrame:
        """读取指定图层数据"""
        return gpd.read_file(self.gpkg_file, layer=layer, where=where_clause, on_invalid="ignore")

    def _transform_crs(self, data: dict) -> dict:
        """转换坐标系统到EPSG:3857"""
        return {key: df.to_crs(epsg=3857) for key, df in data.items()}

    def _create_empty_data(self) -> dict:
        """创建空的数据框"""
        return {key: gpd.GeoDataFrame() for key in ['buildings', 'roads', 'parks', 'water']}

    def create_buffer(self, data: gpd.GeoDataFrame, buffer_size: float) -> gpd.GeoSeries:
        """创建缓冲区"""
        return data.geometry.buffer(buffer_size)

class ShapeGenerator:
    """形状生成器类"""
    def __init__(self, config: Config):
        self.min_dist = config.MIN_DISTANCE
        self.max_dist = config.MAX_DISTANCE

    def _create_point(self, current_point: Point) -> Tuple[Point, float]:
        """生成新的点位"""
        angle = random.uniform(0, 360)
        distance = random.uniform(self.min_dist, self.max_dist)
        dx = distance * cos(angle * pi / 180)
        dy = distance * sin(angle * pi / 180)
        return Point(current_point.x + dx, current_point.y + dy), distance

    def _create_polygon(self, center: Point, distance: float, vertices: int, rotation: float = 0) -> Polygon:
        """创建多边形"""
        points = [(center.x + distance * cos(2 * pi * i / vertices + rotation),
                  center.y + distance * sin(2 * pi * i / vertices + rotation))
                 for i in range(vertices)]
        points.append(points[0])
        return Polygon(points)

    def generate_shapes(self, current_point: Point, shape_type: ShapeType = ShapeType.CIRCLE) -> List[Polygon]:
        """生成形状"""
        distance = random.uniform(self.min_dist, self.max_dist)
        if shape_type == ShapeType.PENTAGON:
            return [self._create_polygon(current_point, distance, 5, int(i * 2 * pi / 3)) 
                   for i in range(3)]
        else:
            return [self._create_polygon(
                Point(current_point.x + distance * cos(i * 2 * pi / 3),
                      current_point.y + distance * sin(i * 2 * pi / 3)),
                distance, 32) for i in range(3)]

class SiteSelection:
    """选址验证类"""
    def __init__(self, config: Config, buildings_gdf: gpd.GeoDataFrame, 
                 parks_gdf: gpd.GeoDataFrame, water_buffer: gpd.GeoSeries, 
                 road_buffer: gpd.GeoSeries):
        self.buildings_gdf = buildings_gdf
        self.parks_gdf = parks_gdf
        self.water_buffer = water_buffer
        self.road_buffer = road_buffer
        self.min_dist = config.MIN_DISTANCE
        self.max_dist = config.MAX_DISTANCE

    def is_valid_point(self, point: Point, valid_points: List[Point], circles: List[Tuple[Polygon, Point]]) -> bool:
        """验证点位是否有效"""
        return (self._check_basic_conditions(point) and 
                self._check_circle_conditions(point, circles) and
                self._check_min_distance(point, valid_points))

    def _check_basic_conditions(self, point: Point) -> bool:
        """检查基本条件"""
        return ((self.buildings_gdf.geometry.contains(point).any() or 
                self.parks_gdf.geometry.contains(point).any()) and
                not any(buffer.contains(point) for buffer in self.water_buffer) and
                not any(buffer.contains(point) for buffer in self.road_buffer))

    def _check_circle_conditions(self, point: Point, circles: List[Tuple[Polygon, Point]]) -> bool:
        """检查圆形条件"""
        if not circles:
            return True
        return not any(self._is_invalid_circle(point, circle, center) 
                      for circle, center in circles)

    def _check_min_distance(self, point: Point, valid_points: List[Point]) -> bool:
        """检查是否满足最小距离要求"""
        return all(point.distance(existing_point) >= self.min_dist for existing_point in valid_points)

    def _is_invalid_circle(self, point: Point, circle: Polygon, center: Point) -> bool:
        """检查是否在无效圆形范围内"""
        if circle.contains(point):
            dist = point.distance(center)
            return dist < self.min_dist or dist > self.max_dist
        return False

def main():
    """主函数"""
    try:
        config = Config()
        geo_manager = GeoDataManager()
        data = geo_manager.data

        # 创建缓冲区
        water_buffer = geo_manager.create_buffer(data['water'], config.WATER_BUFFER)
        road_buffer = geo_manager.create_buffer(data['roads'], config.ROAD_BUFFER)
        print("水域和道路缓冲区生成完成")

        # 初始化验证器和形状生成器
        validator = SiteSelection(config, data['buildings'], data['parks'], water_buffer, road_buffer)
        shape_gen = ShapeGenerator(config)

        # 设置起始点和初始化数据结构
        start_point = gpd.GeoSeries([Point(config.START_POINT)], crs=4326).to_crs(3857)[0]
        valid_points, circles = [start_point], []

        # 生成第一个圆
        first_radius = random.uniform(config.MIN_DISTANCE, config.MAX_DISTANCE)
        circles.append((start_point.buffer(first_radius), start_point))

        print(f"生成的第 1 个点坐标: {gpd.GeoSeries([start_point], crs=3857).to_crs(4326)[0].coords[0]}")

        # 生成其他点位
        attempts = 0
        while len(valid_points) < config.TARGET_POINTS and attempts < config.MAX_ATTEMPTS:
            reference_point = random.choice(valid_points)
            new_point, distance = shape_gen._create_point(reference_point)

            if validator.is_valid_point(new_point, valid_points, circles):
                valid_points.append(new_point)
                circles.append((new_point.buffer(distance), new_point))

                display_point = gpd.GeoSeries([new_point], crs=3857).to_crs(4326)[0]
                print(f"生成的第 {len(valid_points)} 个点坐标: {display_point.x}, {display_point.y}")

            attempts += 1

        if attempts >= config.MAX_ATTEMPTS:
            print(f"达到最大尝试次数 {config.MAX_ATTEMPTS}，共生成 {len(valid_points)} 个有效点")

        # 保存点位结果
        points_gdf = gpd.GeoDataFrame(geometry=valid_points, crs=3857).to_crs(4326)
        points_gdf.to_file(config.OUTPUT_FILE, driver="GPKG", layer="points")
        print(f"已生成{len(valid_points)}个点并保存到 {config.OUTPUT_FILE}")

        # 保存圆形结果
        circles_geometry = [circle for circle, _ in circles]
        circles_gdf = gpd.GeoDataFrame(geometry=circles_geometry, crs=3857).to_crs(4326)
        circles_gdf.to_file(config.CIRCLES_FILE, driver="GPKG", layer="circles")
        print(f"已生成{len(circles)}个圆并保存到 {config.CIRCLES_FILE}")

    except Exception as e:
        print(f"程序运行错误: {e}")

if __name__ == "__main__":
    main()