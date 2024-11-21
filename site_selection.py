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

CRS = 3857

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
    target_points: Optional[int] = None
    output_dir: str = "output"
    score_threshold: float = 0.5
    fields: List[Fields] = field(default_factory=lambda: [
        Fields(field_name="site_id"),
        Fields(field_name="site_longitude"),
        Fields(field_name="site_latitude"),
        Fields(field_name="site_height"),
        Fields(field_name="site_sector", default_value=3),
    ])

@dataclass
class ConstraintType(Enum):
    """约束类型"""
    MUST_WITHIN = auto()
    MUST_OUTSIDE = auto()
    PREFER_WITHIN = auto()
    # PREFER_OUTSIDE = auto()

@dataclass
class SpatialConstraint:
    """空间约束"""
    name: str
    geometry: gpd.GeoDataFrame
    constraint_type: ConstraintType
    priority: int = 0  # 添加优先级字段，数字越小优先级越高

class ConstraintValidator:
    """约束验证器"""
    def __init__(self):
        # self.constraints: List[SpatialConstraint] = []
        self.valid_area: Optional[gpd.GeoDataFrame] = None
        self.prefer_areas: List[gpd.GeoDataFrame] = []  # 存储按优先级排序的区域
        
    def add_constraint(self, constraint: SpatialConstraint):
        """添加并处理约束"""
        # 只保留geometry列，删除其他属性列
        constraint_gdf = gpd.GeoDataFrame(geometry=constraint.geometry.geometry, crs=constraint.geometry.crs).to_crs(CRS)
        
        # self.constraints.append(constraint)
        if constraint.constraint_type == ConstraintType.MUST_WITHIN:
            if self.valid_area is None:
                self.valid_area = constraint_gdf
            else:
                self.valid_area = self.valid_area.overlay(constraint_gdf, how='intersection')
        elif constraint.constraint_type == ConstraintType.MUST_OUTSIDE:
            if self.valid_area is None:
                raise ValueError("MUST_OUTSIDE约束需要先定义一个有效区域范围")
            self.valid_area = self.valid_area.overlay(constraint_gdf, how='difference')
            self.valid_area.to_file(f"{self.config.output_dir}/valid_area.gpkg", driver="GPKG", layer="valid_area")
        elif constraint.constraint_type == ConstraintType.PREFER_WITHIN:
            self.prefer_areas.append((constraint.priority, constraint_gdf))
            
        # 合并有效区域
        # self.valid_area = gpd.GeoDataFrame(geometry=unary_union(self.valid_area.geometry), crs=CRS)
        

    def get_valid_area(self) -> gpd.GeoDataFrame:
        """返回有效区域，按优先级排序，优先级高的区域放到前面"""
        if self.valid_area is None:
            raise ValueError("没有设置任何约束条件")
            
        # 按优先级排序prefer_areas
        self.prefer_areas.sort(key=lambda x: x[0])
        
        # 如果没有优先区域，直接返回有效区域
        if not self.prefer_areas:
            return self.valid_area.explode(ignore_index=True)
            
        # 创建分层的有效区域
        layered_areas = []
        remaining_area = self.valid_area.copy()
        
        # 按优先级处理每个prefer区域
        for _, prefer_area in self.prefer_areas:
            # 与当前剩余区域相交
            current_layer = gpd.overlay(remaining_area, prefer_area, how='intersection')
            if not current_layer.empty:
                layered_areas.append(current_layer)
            # 更新剩余区域
            remaining_area = gpd.overlay(remaining_area, prefer_area, how='difference')
            
        # 添加剩余区域作为最后一层
        if not remaining_area.empty:
            layered_areas.append(remaining_area)
            
        # 合并所有层
        return pd.concat(layered_areas, ignore_index=True).explode(ignore_index=True)
    
    def update_valid_area(self, excluded_area: gpd.GeoDataFrame):
        """更新有效区域，去除已生成点的缓冲区"""
        self.valid_area = gpd.overlay(self.valid_area, excluded_area, how='difference').explode(ignore_index=True)


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
            gdf = gpd.read_file(self.file,where=where,layer=layer).to_crs(CRS)
            if buffer_size is not None:
                # 对每个几何体单独进行buffer操作
                gdf['geometry'] = gdf['geometry'].buffer(buffer_size)
            return gdf
        except Exception as e:
            print(f"读取图层 {layer} 失败: {e}")
            return gpd.GeoDataFrame(geometry=[], crs=CRS)

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

    def create_circle(self, point: Tuple[float, float], radius: float)->gpd.GeoDataFrame:
        return gpd.GeoDataFrame(
            geometry=[point.buffer(radius)], 
            crs=3857
        )
        
        
    def get_random_point(self, search_area: gpd.GeoDataFrame) -> Optional[Point]:
        # 按照DataFrame的顺序处理，因为get_valid_area已经按优先级排序了
        search_area = search_area.explode(ignore_index=True)
        
        # 从高优先级区域开始尝试
        for idx in range(len(search_area)):
            current_poly = search_area.iloc[idx]
            bounds = current_poly.geometry.bounds
            
            # 在当前多边形中尝试生成点
            # local_attempts = min(1000, self.config.max_attempts // len(search_area))
            while True:
                point = Point(random.uniform(bounds[0], bounds[2]), 
                             random.uniform(bounds[1], bounds[3]))
                
                if current_poly.geometry.contains(point):
                    return point
                
        return None

    def generate(self) -> gpd.GeoDataFrame:
        """生成点位"""
        try:
            valid_area = self.validator.get_valid_area()
            valid_area.to_file(f"{self.config.output_dir}/valid_area1.gpkg", driver="GPKG", layer="valid_area")  
            valid_points = []
            
            # 根据是否设置目标点位数创建不同格式的进度条
            if self.config.target_points:
                pbar = tqdm(
                    total=self.config.target_points,
                    desc="生成点位",
                    bar_format='{desc}: {n_fmt}/{total_fmt} [{bar}] {percentage:3.0f}%'
                )
            else:
                pbar = tqdm(
                    desc="生成点位",
                    bar_format='{desc}: {n_fmt} 个点位 [{bar}] {elapsed}',
                    disable=False
                )
            
            while not valid_area.empty:
                if self.config.target_points and len(valid_points) >= self.config.target_points:
                    break
                    
                new_point = self.get_random_point(valid_area)
                if new_point is None:
                    print("\n无法在剩余区域中生成有效点位")
                    break
                    
                valid_points.append(new_point)
                new_circle = self.create_circle(new_point, self.config.min_distance)
                self.validator.update_valid_area(new_circle)
                valid_area = self.validator.get_valid_area()
                
                pbar.update(1)
            
            pbar.close()
            print(f"\n成功生成 {len(valid_points)} 个点位")
            valid_area.to_file(f"{self.config.output_dir}/valid_area.gpkg", driver="GPKG", layer="valid_area")  
            points_gdf = gpd.GeoDataFrame(geometry=valid_points, crs=3857)
            return points_gdf.to_crs(4326)
                
        except Exception as e:
            print(f"生成点位错误: {e}")
            return gpd.GeoDataFrame(geometry=valid_points, crs=3857).to_crs(4326)
        
class FieldsGenerator:
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
            raise ValueError(f"指定的字��� {height_field} 在高度数据中不存在")

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

def equal_epsg(gdf1: gpd.GeoDataFrame, gdf2: gpd.GeoDataFrame)->bool:
    """判断两个GeoDataFrame的坐标系是否相同"""
    return gdf1.crs == gdf2.crs
  
def main():
    """主函数"""
    try:
        # 设置配置参数
        config = GeneratorConfig(
            # target_points=200,
            output_dir="雨花区-1",
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
            where="name='雨花区'"
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

        # field=FieldsGenerator(point_gdf,config=config)
        # field.add_height(gpd.read_file("./osm_data/长沙-20241111-v2.gpkg"))
        # gdf=field.apply_fields()
        point_gdf.to_crs(4326).to_file(
                f"{config.output_dir}/points.gpkg",
                driver="GPKG",
                layer="points"
            )


    except Exception as e:
        print(f"程序运行错误: {e}")
        raise

if __name__ == "__main__":
    main()
    