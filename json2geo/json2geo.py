import json
import argparse
from pathlib import Path
from typing import Dict, List, Any
from enum import Flag, auto

class GeometryTypes(Flag):
    """Binary flags for geometry types"""
    NONE = 0
    POINT = auto()
    LINESTRING = auto()
    POLYGON = auto()
    MULTIPOINT = auto()
    MULTILINESTRING = auto()
    MULTIPOLYGON = auto()
    GEOMETRYCOLLECTION = auto()
    ALL = (POINT | LINESTRING | POLYGON | MULTIPOINT | 
           MULTILINESTRING | MULTIPOLYGON | GEOMETRYCOLLECTION)

def fix_polygon_orientation(coordinates: List[List[float]]) -> bool:
    """
    Fix polygon ring orientation according to the right-hand rule:
    - Exterior rings should be counterclockwise
    - Interior rings (holes) should be clockwise
    Returns True if any changes were made
    """
    def calculate_area(ring: List[List[float]]) -> float:
        """Calculate the signed area of a ring"""
        area = 0
        for i in range(len(ring) - 1):
            j = (i + 1)
            area += ring[i][0] * ring[j][1]
            area -= ring[j][0] * ring[i][1]
        return area / 2

    def reverse_ring(ring: List[List[float]]) -> None:
        """Reverse the order of coordinates in a ring"""
        ring.reverse()

    changed = False
    # First ring is exterior (should be counterclockwise)
    area = calculate_area(coordinates[0])
    if area < 0:  # If clockwise, reverse it
        reverse_ring(coordinates[0])
        changed = True

    # Other rings are interior (should be clockwise)
    for ring in coordinates[1:]:
        area = calculate_area(ring)
        if area > 0:  # If counterclockwise, reverse it
            reverse_ring(ring)
            changed = True

    return changed

def fix_geometry_orientation(geometry: Dict[str, Any]) -> bool:
    """Fix orientation of Polygons and MultiPolygons"""
    if not geometry or 'type' not in geometry:
        return False

    changed = False
    if geometry['type'] == 'Polygon':
        changed = fix_polygon_orientation(geometry['coordinates'])
    elif geometry['type'] == 'MultiPolygon':
        for polygon in geometry['coordinates']:
            if fix_polygon_orientation(polygon):
                changed = True
    return changed

class GeoJSONParser:
    def __init__(self, limit: int = None, require_geometry: bool = True, 
                 geometry_types: GeometryTypes = GeometryTypes.ALL):
        self.features: List[Dict[str, Any]] = []
        self.limit = limit
        self.require_geometry = require_geometry
        self.geometry_types = geometry_types
    
    def is_valid_geojson(self, data: Dict[str, Any]) -> bool:
        """Check if the data is valid GeoJSON"""
        if not isinstance(data, dict):
            return False
            
        if 'type' not in data:
            return False
            
        if data['type'] == 'Feature':
            has_properties = 'properties' in data
            has_geometry = 'geometry' in data and data['geometry'] is not None
            # Determine if geometry is required based on require_geometry parameter
            return has_properties and (not self.require_geometry or has_geometry)
            
        if data['type'] == 'FeatureCollection':
            return 'features' in data and isinstance(data['features'], list)
            
        return True
    
    def is_valid_feature(self, feature: Dict[str, Any]) -> bool:
        """Check if a single feature is valid and matches selected geometry types"""
        if not isinstance(feature, dict) or 'type' not in feature:
            return False
            
        has_properties = 'properties' in feature
        has_geometry = 'geometry' in feature and feature['geometry'] is not None
        
        if not has_properties or (self.require_geometry and not has_geometry):
            return False
            
        # If geometry is not required, accept features without geometry
        if not has_geometry and not self.require_geometry:
            return True
            
        # Check geometry type
        geometry = feature['geometry']
        geometry_type = geometry['type']
        
        type_flag = getattr(GeometryTypes, geometry_type.upper(), GeometryTypes.NONE)
        return bool(self.geometry_types & type_flag)
    
    def extract_features(self, data: Dict[str, Any]) -> None:
        """Extract GeoJSON features from data"""
        if self.limit and len(self.features) >= self.limit:
            return
            
        if 'property_geojson' in data:
            geojson_data = data['property_geojson']
            if not self.is_valid_geojson(geojson_data):
                return
                
            if geojson_data['type'] == 'Feature':
                if self.is_valid_feature(geojson_data):
                    if not self.limit or len(self.features) < self.limit:
                        self.features.append(geojson_data)
            elif geojson_data['type'] == 'FeatureCollection':
                valid_features = [f for f in geojson_data['features'] if self.is_valid_feature(f)]
                remaining = self.limit - len(self.features) if self.limit else None
                if remaining is not None:
                    self.features.extend(valid_features[:remaining])
                else:
                    self.features.extend(valid_features)
    
    def parse_file(self, input_path: str) -> None:
        """Parse input file"""
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
                
            if isinstance(json_data, dict) and 'data' in json_data:
                for item in json_data['data']:
                    if self.limit and len(self.features) >= self.limit:
                        break
                    self.extract_features(item)
            else:
                self.extract_features(json_data)
                
        except Exception as e:
            print(f"Error parsing file: {str(e)}")
    
    def save_geojson(self, output_path: str) -> None:
        """Save to GeoJSON file"""
        try:
            # Fix polygon orientations before saving
            fixed_count = 0
            for feature in self.features:
                if 'geometry' in feature and feature['geometry']:
                    if fix_geometry_orientation(feature['geometry']):
                        fixed_count += 1

            feature_collection = {
                "type": "FeatureCollection",
                "features": self.features
            }
            
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(feature_collection, f, ensure_ascii=False, indent=2)
                
            print(f"Successfully extracted {len(self.features)} features to {output_path}")
            if fixed_count > 0:
                print(f"Fixed orientation of {fixed_count} polygons")
            
        except Exception as e:
            print(f"Error saving file: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description='Extract GeoJSON data from JSON response')
    parser.add_argument('-i', '--input', required=True, help='Input JSON file path')
    parser.add_argument('-o', '--output', required=True, help='Output GeoJSON file path')
    parser.add_argument('-l', '--limit', type=int, help='Limit the number of features to extract')
    parser.add_argument('--allow-empty-geom', action='store_true', 
                       help='Include features without geometry field')
    parser.add_argument('-f', '--flag', type=lambda x: int(x, 0), default=0x7F,
                       help='''Binary flag for geometry types (default: 0x7F, all types).
Binary bits from right to left:
  bit 0 (0b000001, 0x01): POINT
  bit 1 (0b000010, 0x02): LINESTRING
  bit 2 (0b000100, 0x04): POLYGON
  bit 3 (0b001000, 0x08): MULTIPOINT
  bit 4 (0b010000, 0x10): MULTILINESTRING
  bit 5 (0b100000, 0x20): MULTIPOLYGON
  bit 6 (0b1000000, 0x40): GEOMETRYCOLLECTION
Examples:
  0b000011 (0x03): Points and LineStrings
  0b000101 (0x05): Points and Polygons
  0b111111 (0x3F): All except GeometryCollection
  0b1111111 (0x7F): All types''')
    
    args = parser.parse_args()
    
    # Generate output filename with argument information
    if args.output:
        output_path = Path(args.output)
        base_name = output_path.stem
        extension = output_path.suffix
        
        # Add flags to filename
        flags = []
        if args.limit:
            flags.append(f"l{args.limit}")
        if args.allow_empty_geom:
            flags.append("allownongeo")
        flags.append(f"f{args.flag:02x}")  # Add flag in hex format
        
        # Save the original output path for later
        original_output_path = output_path.parent / f"{base_name}_{'_'.join(flags)}{extension}"
    
    # Convert flag to GeometryTypes
    geometry_types = GeometryTypes(args.flag)
    
    geojson_parser = GeoJSONParser(
        limit=args.limit,
        require_geometry=not args.allow_empty_geom,
        geometry_types=geometry_types
    )
    geojson_parser.parse_file(args.input)
    
    # Check and fix orientations before saving
    fixed_count = 0
    for feature in geojson_parser.features:
        if 'geometry' in feature and feature['geometry']:
            if fix_geometry_orientation(feature['geometry']):
                fixed_count += 1
    
    # Add orientation fix information to filename if needed
    if fixed_count > 0:
        base_name = original_output_path.stem
        output_path = original_output_path.parent / f"{base_name}_fixori{extension}"
    else:
        output_path = original_output_path
    
    geojson_parser.save_geojson(str(output_path))

if __name__ == "__main__":
    main()
