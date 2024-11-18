# 导入所需的库
import random
from shapely.geometry import Point, Polygon
from math import cos, sin, pi  
from enum import Enum
import geopandas as gpd 
from pathlib import Path
from dataclasses import dataclass
from typing import List, Tuple
from shapely.ops import unary_union
import pandas as pd

class PointGeneratorConfig:
    """点位生成器配置"""
    def __init__(self,
                 min_distance: float = 220,     # 最小距离
                 max_distance: float = 550,     # 最大距离
                 water_buffer: float = 40,      # 水域缓冲区
                 road_buffer: float = 60,       # 道路缓冲区
                 max_attempts: int = 100000,    # 最大尝试次数 
                 target_points: int = 500,      # 目标点数量
                 start_point: Tuple[float,float] = (112.998061, 28.17708), # 起始点
                 output_dir: str = "output"     # 输出目录
                ):
        self.min_distance = min_distance
        self.max_distance = max_distance  
        self.water_buffer = water_buffer
        self.road_buffer = road_buffer
        self.max_attempts = max_attempts
        self.target_points = target_points
        self.start_point = start_point
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    @property    
    def points_file(self) -> str:
        return str(self.output_dir / "points.gpkg")

    @property
    def circles_file(self) -> str:
        return str(self.output_dir / "circles.gpkg")

    @property  
    def union_file(self) -> str:
        return str(self.output_dir / "union.gpkg")

class GeoDataManager:
    """地理数据管理类"""
    def __init__(self, gpkg_file: str, config: PointGeneratorConfig):
        self.gpkg_file = Path(gpkg_file)
        if not self.gpkg_file.exists():
            raise FileNotFoundError(f"GPKG文件未找到: {gpkg_file}")
        self.config = config    
        self.data = self._load_data()

        # 创建各类空间对象
        self.buildings = self.data['buildings']
        self.parks = self.data['parks']
        self.roads = gpd.GeoDataFrame(geometry=self.data['roads'].buffer(config.road_buffer), crs=3857)
        self.water = gpd.GeoDataFrame(geometry=self.data['water'].buffer(config.water_buffer), crs=3857)

    def _load_data(self) -> dict:
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
        return gpd.read_file(self.gpkg_file, layer=layer, where=where_clause, on_invalid="ignore")

    def _transform_crs(self, data: dict) -> dict:
        return {key: gdf.to_crs(epsg=3857) for key, gdf in data.items()}

    def _create_empty_data(self) -> dict:
        return {key: gpd.GeoDataFrame() for key in ['buildings', 'roads', 'parks', 'water']}

    def create_buffer(self, data: gpd.GeoDataFrame, buffer_size: float) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(geometry=data.geometry.buffer(buffer_size), crs=data.crs)

class PointGenerator:
    """点位生成器"""
    def __init__(self, config: PointGeneratorConfig, geo_manager: GeoDataManager):
        self.config = config
        self.geo_manager = geo_manager

    def create_ring(self, point: Point) -> gpd.GeoDataFrame:
        outer_circle = gpd.GeoDataFrame(geometry=[point.buffer(self.config.max_distance)], crs=3857)
        inner_circle = gpd.GeoDataFrame(geometry=[point.buffer(self.config.min_distance)], crs=3857)
        diff = gpd.overlay(outer_circle, inner_circle, how='difference')
        if not diff.empty:
            return diff
        raise Exception("无法创建有效的环形区域")

    def get_random_point(self, search_area: gpd.GeoDataFrame) -> Point:
        minx, miny, maxx, maxy = search_area.total_bounds
        attempts = 0
        while attempts < self.config.max_attempts:
            point = gpd.GeoDataFrame(
                geometry=[Point(random.uniform(minx, maxx), random.uniform(miny, maxy))],
                crs=3857
            )

            # 使用空间操作进行检查
            if (gpd.tools.sjoin(point, search_area, how="inner", predicate="within").shape[0] > 0 and
                (gpd.tools.sjoin(point, self.geo_manager.buildings, how="inner", predicate="within").shape[0] > 0 or
                 gpd.tools.sjoin(point, self.geo_manager.parks, how="inner", predicate="within").shape[0] > 0) and
                gpd.tools.sjoin(point, self.geo_manager.roads, how="inner", predicate="within").shape[0] == 0 and
                gpd.tools.sjoin(point, self.geo_manager.water, how="inner", predicate="within").shape[0] == 0):
                return point.geometry.iloc[0]
            attempts += 1
        raise Exception("无法在有效区域内找到合适的点位")

    def generate(self):
        """生成点位"""
        try:
            # 创建起始点GeoDataFrame
            start_point = gpd.GeoDataFrame(
                geometry=[Point(self.config.start_point)], 
                crs=4326
            ).to_crs(3857).geometry.iloc[0]

            valid_points_gdf = gpd.GeoDataFrame(geometry=[start_point], crs=3857)

            # 初始圆环
            first_ring = self.create_ring(start_point)
            rings_gdf = first_ring 
            union_area = gpd.GeoDataFrame(geometry=rings_gdf.geometry, crs=3857)

            # 生成点位
            for i in range(1, self.config.target_points):
                new_point = self.get_random_point(union_area)
                valid_points_gdf = pd.concat([
                    valid_points_gdf, 
                    gpd.GeoDataFrame(geometry=[new_point], crs=3857)
                ])

                new_ring = self.create_ring(new_point)
                # 修改union计算方式
                # 先计算两个圆环的并集 
                temp_union = gpd.overlay(union_area, new_ring, how='union')
                # 合并相连的geometry
                temp_union = gpd.GeoDataFrame(geometry=[unary_union(temp_union.geometry)], crs=3857)
                # 计算两个内圈
                old_inner = gpd.GeoDataFrame(geometry=[Point(p).buffer(self.config.min_distance) for p in valid_points_gdf.geometry[:-1]], crs=3857)
                new_inner = gpd.GeoDataFrame(geometry=[new_point.buffer(self.config.min_distance)], crs=3857)
                # 从并集中去除内圈区域
                union_area = gpd.overlay(temp_union, old_inner, how='difference',keep_geom_type=True)
                union_area = gpd.overlay(union_area, new_inner, how='difference',keep_geom_type=True)

                display_point = gpd.GeoDataFrame(
                    geometry=[new_point], 
                    crs=3857
                ).to_crs(4326).geometry.iloc[0]
                print(f"生成的第 {i+1} 个点坐标: {display_point.x}, {display_point.y}")

            # 保存结果
            valid_points_gdf.to_crs(4326).to_file(
                self.config.points_file, 
                driver="GPKG", 
                layer="points"
            )
            print(f"已生成{len(valid_points_gdf)}个点并保存到 {self.config.points_file}")

            union_area.to_crs(4326).to_file(
                self.config.union_file, 
                driver="GPKG", 
                layer="union"
            )
            print(f"已保存并集区域到 {self.config.union_file}")

        except Exception as e:
            print(f"生成点位错误: {e}")

def main():
    """主函数"""
    try:
        config = PointGeneratorConfig(target_points=1000)
        geo_manager = GeoDataManager("osm_data/长沙.gpkg", config)
        generator = PointGenerator(config, geo_manager)
        generator.generate()
    except Exception as e:
        print(f"程序运行错误: {e}")

if __name__ == "__main__":
    main()