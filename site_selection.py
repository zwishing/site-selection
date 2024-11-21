from dataclasses import dataclass, field
from typing import Any, List, Tuple, Optional
from pathlib import Path
from enum import Enum, auto
import random
from shapely.geometry import Point
import geopandas as gpd
import pandas as pd
from tqdm import tqdm
from shapely.ops import unary_union
import numpy as np

@dataclass
class Fields:
    field_name: str
    default_value: Optional[object] = None
    dtype: Optional[str] = None

@dataclass
class GeneratorConfig:
    """生成器配置"""
    min_distance: float = 230 
    max_distance: float = 580
    max_attempts: int = 1000000
    target_points: int = 300
    start_point: Tuple[float, float] = (112.998061, 28.17708)
    output_dir: str = "output"
    score_threshold: float = 0.5
    fields: List[Fields] = field(default_factory=lambda: [
        Fields(field_name="site_id"),
        Fields(field_name="site_longitude"),
        Fields(field_name="site_latitude"),
        Fields(field_name="site_height"),
        Fields(field_name="site_sector", default_value=3),
    ])


class ConstraintType(Enum):
    """约束类型"""
    MUST_WITHIN = auto()
    MUST_OUTSIDE = auto()
    PREFER_WITHIN = auto()
    PREFER_OUTSIDE = auto()

@dataclass
class SpatialConstraint:
    """空间约束"""
    name: str
    geometry: gpd.GeoDataFrame
    constraint_type: ConstraintType
    weight: float = 1.0

    def check_point(self, point: Point) -> Tuple[bool, float]:
        """检查点是否满足约束"""
        points_gdf = gpd.GeoDataFrame({'geometry': [point]}, crs=self.geometry.crs)
        # 空间连接，找出点在哪些面内
        within = not gpd.sjoin(points_gdf, self.geometry, predicate='within').empty
        
        if self.constraint_type == ConstraintType.MUST_WITHIN:
            return within, 1.0 if within else 0.0
        elif self.constraint_type == ConstraintType.MUST_OUTSIDE:
            return not within, 1.0 if not within else 0.0
        elif self.constraint_type == ConstraintType.PREFER_WITHIN:
            return True, self.weight if within else 0.0
        else:  # PREFER_OUTSIDE
            return True, self.weight if not within else 0.0

class ConstraintValidator:
    """约束验证器"""
    def __init__(self):
        self.constraints: List[SpatialConstraint] = []
        
    def add_constraint(self, constraint: SpatialConstraint):
        self.constraints.append(constraint)
    
    def validate(self, point: Point) -> Tuple[bool, float]:
        """验证点位"""
        score = 0.0
        
        for constraint in self.constraints:
            valid, constraint_score = constraint.check_point(point)
            if not valid:
                return False, 0.0
            score += constraint_score
            
        return True, score

class GeoFeatureManager:
    """地理要素管理器"""
    def __init__(self, file: str):
        self.file = Path(file)
        if not self.file.exists():
            raise FileNotFoundError(f"矢量数据文件未找到: {file}")
        
    def read_feature(self, 
                    where: str, 
                    layer: Optional[str] = None, 
                    buffer_size: Optional[float] = None) -> gpd.GeoDataFrame:
        """读取地理要素"""
        try:
            gdf = gpd.read_file(self.file,where=where,layer=layer).to_crs(3857)
            if buffer_size is not None:
                # 对每个几何体单独进行buffer操作
                gdf['geometry'] = gdf['geometry'].buffer(buffer_size)
            return gdf
        except Exception as e:
            print(f"读取图层 {layer} 失败: {e}")
            return gpd.GeoDataFrame(geometry=[], crs=3857)

class PointGenerator:
    """点位生成器"""
    def __init__(self, config: GeneratorConfig, validator: ConstraintValidator):
        self.config = config
        self.validator = validator
        Path(config.output_dir).mkdir(exist_ok=True)
    
    def create_ring(self, point: Tuple[float, float]) -> gpd.GeoDataFrame:
        """创建环形区域"""
        if isinstance(point, gpd.GeoDataFrame):
            point = Point(point.geometry.iloc[0].x, point.geometry.iloc[0].y)
        elif isinstance(point, Point):
            pass
        else:
            point = Point(point[0], point[1])
            
        outer_circle = point.buffer(self.config.max_distance)
        inner_circle = point.buffer(self.config.min_distance)
        ring = outer_circle.difference(inner_circle)
        return gpd.GeoDataFrame(geometry=[ring], crs=3857)
    
    def create_hexagon(self, point: Tuple[float, float])->gpd.GeoDataFrame:
        pass


    def get_random_point(self, search_area: gpd.GeoDataFrame) -> Optional[Point]:
        # 获取每个多边形的面积
        search_area=search_area.explode(ignore_index=True)
        areas = search_area.area
        total_area = areas.sum()
        
        attempts = 0
        while attempts < self.config.max_attempts:
            # 根据面积权重随机选择一个多边形
            chosen_poly = search_area.iloc[np.random.choice(len(search_area), p=areas/total_area)]
            bounds = chosen_poly.geometry.bounds
            
            # 在选中的多边形范围内生成随机点
            point = Point(random.uniform(bounds[0], bounds[2]), 
                         random.uniform(bounds[1], bounds[3]))
            
            if chosen_poly.geometry.contains(point):
                is_valid, _ = self.validator.validate(point)
                if is_valid:
                    return point
            attempts += 1
        return None

    def generate(self)->gpd.GeoDataFrame:
        """生成点位"""
        try:
            # 创建起始点
            start_point = gpd.GeoDataFrame(
                geometry=[Point(self.config.start_point)], 
                crs=4326
            ).to_crs(3857).geometry.iloc[0]

            valid_points = [start_point]
            union_area = self.create_ring(start_point)
            
            with tqdm(total=self.config.target_points,initial=1) as pbar:
                while len(valid_points) < self.config.target_points:
                    new_point = self.get_random_point(union_area)
                    if new_point is None:
                        print(f"\n无法在第{len(valid_points)+1}次找到有效点位")
                        break

                    valid_points.append(new_point)
                    new_ring = self.create_ring(new_point)
                    
                    # 先计算两个圆环的并集 
                    temp_union = gpd.overlay(union_area, new_ring, how='union')
                    # 合并相连的geometry
                    temp_union = gpd.GeoDataFrame(geometry=[unary_union(temp_union.geometry)], crs=3857)
                    # 计算两个内圈
                    old_inner = gpd.GeoDataFrame(geometry=[Point(p).buffer(self.config.min_distance) for p in valid_points], crs=3857)
                    new_inner = gpd.GeoDataFrame(geometry=[new_point.buffer(self.config.min_distance)], crs=3857)
                    # 从并集中去除内圈区域
                    union_area = gpd.overlay(temp_union, old_inner, how='difference',keep_geom_type=True)
                    union_area = gpd.overlay(union_area, new_inner, how='difference',keep_geom_type=True)

                    pbar.update(1)

            # 保存结果
            points_gdf = gpd.GeoDataFrame(geometry=valid_points, crs=3857)
            union_area.to_crs(4326).to_file(
                f"{self.config.output_dir}/union.gpkg",
                driver="GPKG",
                layer="union"
            )
            return points_gdf.to_crs(4326)
            # points_gdf.to_crs(4326).to_file(
            #     f"{self.config.output_dir}/points.gpkg",
            #     driver="GPKG",
            #     layer="points"
            # )
            
            
            
            # print(f"\n已生成 {len(valid_points)} 个点位")
            
        except Exception as e:
            print(f"生成点位错误: {e}")
            return points_gdf.to_crs(4326)
        
class FieldsAdd:
    def __init__(self, gdf: gpd.GeoDataFrame, config: GeneratorConfig):
        """
        初始化Fields管理器
        
        :param gdf: 地理数据框
        :param config: 字段配置列表
        """
        self.gdf = gdf
        self.config = config.fields
        
        # 自动识别ID和高度字段
        self.id_field = next((field.field_name for field in self.config if "id" in field.field_name.lower()), "site_id")
        self.height_field = next((field.field_name for field in self.config if "height" in field.field_name.lower()), "site_height")
        self.longitude_field = next((field.field_name for field in self.config if "longitude" in field.field_name.lower()), "site_longitude")
        self.latitude_field = next((field.field_name for field in self.config if "latitude" in field.field_name.lower()), "site_latitude")

    def add_id(self, start: int = 0):
        """
        添加自增ID字段
        
        :param start: ID起始值
        """
        self.gdf[self.id_field] = range(start, len(self.gdf) + start)

    def add_height(self, height_gdf: gpd.GeoDataFrame, height_field: str = "height"):
        """
        从高度数据中添加高度信息
        
        :param height_gdf: 包含高度信息的地理数据框
        :param height_field: 高度字段名
        """
        if height_field not in height_gdf.columns:
            raise ValueError(f"指定的字段 {height_field} 在高度数据中不存在")

        height_gdf = height_gdf.to_crs(self.gdf.crs)
        joined_gdf = gpd.sjoin(self.gdf, height_gdf, how="left", predicate="within")
        self.gdf[self.height_field] = joined_gdf[height_field]

    def add_coordinates(self):
        """添加经纬度坐标字段"""
        self.gdf[self.longitude_field] = self.gdf.geometry.x
        self.gdf[self.latitude_field] = self.gdf.geometry.y

    def add_custom_fields(self):
        """
        根据配置添加自定义字段
        """
        for field_config in self.config:
            if field_config.field_name not in self.gdf.columns:
                if field_config.default_value is None:
                    # 使用dtype创建空字段
                    self.gdf[field_config.field_name] = field_config.dtype()
                else:
                    # 使用默认值填充
                    self.gdf[field_config.field_name] = field_config.default_value

    def apply_fields(self)->gpd.GeoDataFrame:
        """
        应用所有字段处理方法
        """
        self.add_id()  # 添加ID字段
        self.add_coordinates()  # 添加坐标字段
        self.add_custom_fields()  # 添加其他自定义字段
        return self.gdf


def category_num(value):
    """
    """
    if value=="城区":
        return 9
    elif value == "县城":
        return 6
    elif value == "郊区":
        return 4
    elif value=="农村":
        return 2
    
def main():
    """主函数"""
    try:
        # 设置配置参数
        config = GeneratorConfig(
            target_points=400,
            output_dir="id-9",
            start_point=(112.982318, 28.188614)
        )
        
        # 初始化管理器和读取数据
        geo_manager = GeoFeatureManager("osm_data/长沙osm-面.gpkg")
        line = GeoFeatureManager("osm_data/长沙osm-多线.gpkg")
        boundary = GeoFeatureManager("osm_data/长沙市区县.shp")
        
        print("正在读取地理数据...")
        buildings = geo_manager.read_feature(
            where="building IS NOT NULL"
        )
        parks = geo_manager.read_feature(
            where="leisure='park'"
        )
        roads = line.read_feature(
            where="highway IS NOT NULL",
            buffer_size=60
        )
        water = geo_manager.read_feature(
            where="natural='water'",
            buffer_size=40
        )

        authority_boundary = boundary.read_feature(
            where="id=9"
        )

        
        # 创建验证器并添加约束
        validator = ConstraintValidator()
        
        # 合并建筑和公园数据
        valid_areas = pd.concat([buildings, parks])
        if not valid_areas.empty:
            validator.add_constraint(SpatialConstraint(
                "必须在建筑或公园内",
                valid_areas,
                ConstraintType.MUST_WITHIN
            ))

        if not authority_boundary.empty:
            validator.add_constraint(SpatialConstraint(
                "必须在雨花区",
                authority_boundary,
                ConstraintType.MUST_WITHIN
            ))
        
        if not roads.empty:
            validator.add_constraint(SpatialConstraint(
                "必须远离道路",
                roads,
                ConstraintType.MUST_OUTSIDE
            ))
        
        if not water.empty:
            validator.add_constraint(SpatialConstraint(
                "必须远离水体",
                water,
                ConstraintType.MUST_OUTSIDE
            ))
        
        # 创建并运行生成器
        print("开始生成点位...")
        generator = PointGenerator(config, validator)
        point_gdf = generator.generate()

        field=FieldsAdd(point_gdf,config=config)
        field.add_height(gpd.read_file("./osm_data/长沙-20241111-v2.gpkg"))
        gdf=field.apply_fields()
        gdf.to_crs(4326).to_file(
                f"{config.output_dir}/points.gpkg",
                driver="GPKG",
                layer="points"
            )


    except Exception as e:
        print(f"程序运行错误: {e}")
        raise

if __name__ == "__main__":
    main()