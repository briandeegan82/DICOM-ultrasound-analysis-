#!/usr/bin/env python3
"""
DICOM File Extractor
A script to open DICOM files and extract images and metadata.
"""

import os
import sys
import argparse
from pathlib import Path
import json
from typing import Dict, Any, Optional

try:
    import pydicom
    from pydicom.dataset import Dataset
    import numpy as np
    from PIL import Image
except ImportError as e:
    print(f"Error: Missing required library. Please install: pip install pydicom numpy pillow")
    print(f"Missing: {e.name}")
    sys.exit(1)


class DICOMExtractor:
    """Class to extract images and metadata from DICOM files."""
    
    def __init__(self, dicom_path: str):
        """
        Initialize the DICOM extractor.
        
        Args:
            dicom_path: Path to the DICOM file
        """
        self.dicom_path = Path(dicom_path)
        if not self.dicom_path.exists():
            raise FileNotFoundError(f"DICOM file not found: {dicom_path}")
        
        self.dataset: Optional[Dataset] = None
        self.pixel_array: Optional[np.ndarray] = None
        
    def load(self) -> None:
        """Load the DICOM file."""
        try:
            self.dataset = pydicom.dcmread(str(self.dicom_path))
            print(f"Successfully loaded DICOM file: {self.dicom_path.name}")
        except Exception as e:
            raise ValueError(f"Failed to read DICOM file: {e}")
    
    def extract_image(self) -> np.ndarray:
        """
        Extract the image/pixel array from the DICOM file.
        
        Returns:
            numpy array containing the pixel data
        """
        if self.dataset is None:
            self.load()
        
        try:
            # Check if pixel data exists
            if hasattr(self.dataset, 'pixel_array'):
                self.pixel_array = self.dataset.pixel_array
                print(f"Image extracted: Shape {self.pixel_array.shape}, "
                      f"Dtype {self.pixel_array.dtype}")
                
                # Check if it's a sequence
                if self.is_sequence():
                    num_frames = self.get_num_frames()
                    print(f"Detected image sequence with {num_frames} frames")
                
                return self.pixel_array
            else:
                raise ValueError("No pixel data found in DICOM file")
        except Exception as e:
            raise ValueError(f"Failed to extract image: {e}")
    
    def is_sequence(self) -> bool:
        """
        Check if the pixel array contains a sequence of images.
        
        Returns:
            True if the array represents a sequence of images
        """
        if self.pixel_array is None:
            self.extract_image()
        
        # Sequences typically have 4 dimensions (time/frames, height, width, channels)
        # or 3 dimensions where first dimension is frames
        return len(self.pixel_array.shape) >= 3 and (
            len(self.pixel_array.shape) == 4 or
            (len(self.pixel_array.shape) == 3 and self.pixel_array.shape[0] > 1)
        )
    
    def get_num_frames(self) -> int:
        """
        Get the number of frames in the sequence.
        
        Returns:
            Number of frames (1 if not a sequence)
        """
        if self.pixel_array is None:
            self.extract_image()
        
        if not self.is_sequence():
            return 1
        
        # First dimension is typically the frame dimension
        return self.pixel_array.shape[0]
    
    def get_frame(self, frame_index: int) -> np.ndarray:
        """
        Get a specific frame from the sequence.
        
        Args:
            frame_index: Index of the frame to extract (0-based)
        
        Returns:
            numpy array containing the frame
        """
        if self.pixel_array is None:
            self.extract_image()
        
        if not self.is_sequence():
            if frame_index == 0:
                return self.pixel_array
            else:
                raise ValueError("Not a sequence. Use frame_index=0 or extract_image()")
        
        num_frames = self.get_num_frames()
        if frame_index < 0 or frame_index >= num_frames:
            raise ValueError(f"Frame index {frame_index} out of range [0, {num_frames-1}]")
        
        return self.pixel_array[frame_index]
    
    def get_metadata(self, include_private: bool = False) -> Dict[str, Any]:
        """
        Extract metadata from the DICOM file.
        
        Args:
            include_private: Whether to include private tags (default: False)
        
        Returns:
            Dictionary containing metadata
        """
        if self.dataset is None:
            self.load()
        
        metadata = {}
        
        for element in self.dataset:
            # Skip pixel data (too large to include in metadata)
            if element.tag == pydicom.tag.Tag('PixelData'):
                metadata[str(element.tag)] = f"<Pixel Data: {element.VR} - Size: {len(element.value)} bytes>"
                continue
            
            # Skip private tags if not requested
            if not include_private and element.tag.is_private:
                continue
            
            tag_key = str(element.tag)
            tag_name = element.keyword if hasattr(element, 'keyword') else tag_key
            
            try:
                # Try to get the value
                value = element.value
                
                # Handle sequences
                if isinstance(value, list) and len(value) > 0 and isinstance(value[0], Dataset):
                    metadata[tag_key] = {
                        'keyword': tag_name,
                        'VR': element.VR,
                        'value': f"<Sequence with {len(value)} items>"
                    }
                # Handle binary data
                elif isinstance(value, bytes):
                    metadata[tag_key] = {
                        'keyword': tag_name,
                        'VR': element.VR,
                        'value': f"<Binary data: {len(value)} bytes>"
                    }
                else:
                    metadata[tag_key] = {
                        'keyword': tag_name,
                        'VR': element.VR,
                        'value': str(value) if value is not None else None
                    }
            except Exception as e:
                metadata[tag_key] = {
                    'keyword': tag_name,
                    'VR': element.VR,
                    'value': f"<Error reading value: {e}>"
                }
        
        return metadata
    
    def get_common_metadata(self) -> Dict[str, Any]:
        """
        Extract commonly used metadata fields.
        
        Returns:
            Dictionary with common metadata fields
        """
        if self.dataset is None:
            self.load()
        
        common_fields = {
            'Patient Name': getattr(self.dataset, 'PatientName', 'N/A'),
            'Patient ID': getattr(self.dataset, 'PatientID', 'N/A'),
            'Patient Birth Date': getattr(self.dataset, 'PatientBirthDate', 'N/A'),
            'Patient Sex': getattr(self.dataset, 'PatientSex', 'N/A'),
            'Study Date': getattr(self.dataset, 'StudyDate', 'N/A'),
            'Study Time': getattr(self.dataset, 'StudyTime', 'N/A'),
            'Study Description': getattr(self.dataset, 'StudyDescription', 'N/A'),
            'Series Description': getattr(self.dataset, 'SeriesDescription', 'N/A'),
            'Modality': getattr(self.dataset, 'Modality', 'N/A'),
            'Manufacturer': getattr(self.dataset, 'Manufacturer', 'N/A'),
            'Manufacturer Model Name': getattr(self.dataset, 'ManufacturerModelName', 'N/A'),
            'Image Type': getattr(self.dataset, 'ImageType', 'N/A'),
            'Slice Thickness': getattr(self.dataset, 'SliceThickness', 'N/A'),
            'Pixel Spacing': getattr(self.dataset, 'PixelSpacing', 'N/A'),
            'Rows': getattr(self.dataset, 'Rows', 'N/A'),
            'Columns': getattr(self.dataset, 'Columns', 'N/A'),
            'Bits Allocated': getattr(self.dataset, 'BitsAllocated', 'N/A'),
            'Bits Stored': getattr(self.dataset, 'BitsStored', 'N/A'),
            'Samples per Pixel': getattr(self.dataset, 'SamplesPerPixel', 'N/A'),
            'Photometric Interpretation': getattr(self.dataset, 'PhotometricInterpretation', 'N/A'),
        }
        
        return common_fields
    
    def _normalize_image(self, image_data: np.ndarray, normalize: bool = True) -> np.ndarray:
        """
        Normalize image data to 0-255 range.
        
        Args:
            image_data: Image array to normalize
            normalize: Whether to normalize pixel values
        
        Returns:
            Normalized image array
        """
        if normalize:
            if image_data.max() > image_data.min():
                image_data = ((image_data - image_data.min()) / 
                             (image_data.max() - image_data.min()) * 255).astype(np.uint8)
            else:
                image_data = np.zeros_like(image_data, dtype=np.uint8)
        return image_data
    
    def _array_to_image(self, image_data: np.ndarray) -> Image.Image:
        """
        Convert numpy array to PIL Image.
        
        Args:
            image_data: Image array
        
        Returns:
            PIL Image object
        """
        # Handle different image types
        if len(image_data.shape) == 2:
            # Grayscale image
            return Image.fromarray(image_data, mode='L')
        elif len(image_data.shape) == 3:
            # Color image
            if image_data.shape[2] == 3:
                return Image.fromarray(image_data, mode='RGB')
            elif image_data.shape[2] == 4:
                return Image.fromarray(image_data, mode='RGBA')
            else:
                # Take first channel if more than 4 channels
                return Image.fromarray(image_data[:, :, 0], mode='L')
        else:
            raise ValueError(f"Unsupported image shape: {image_data.shape}")
    
    def save_image(self, output_path: Optional[str] = None, 
                   format: str = 'PNG', normalize: bool = True,
                   frame_index: Optional[int] = None) -> str:
        """
        Save the extracted image to a file.
        For sequences, saves a single frame if frame_index is specified,
        otherwise saves the first frame.
        
        Args:
            output_path: Output file path (default: input filename with new extension)
            format: Image format (PNG, JPEG, etc.)
            normalize: Whether to normalize pixel values to 0-255 range
            frame_index: For sequences, which frame to save (default: 0/first frame)
        
        Returns:
            Path to saved image
        """
        if self.pixel_array is None:
            self.extract_image()
        
        # Handle sequences
        if self.is_sequence():
            if frame_index is None:
                frame_index = 0
            image_data = self.get_frame(frame_index)
        else:
            image_data = self.pixel_array.copy()
        
        # Determine output path
        if output_path is None:
            base_name = self.dicom_path.stem
            if self.is_sequence() and frame_index is not None:
                output_path = self.dicom_path.parent / f"{base_name}_frame_{frame_index:04d}.{format.lower()}"
            else:
                output_path = self.dicom_path.with_suffix(f'.{format.lower()}')
        else:
            output_path = Path(output_path)
        
        # Normalize and convert
        image_data = self._normalize_image(image_data, normalize)
        img = self._array_to_image(image_data)
        
        img.save(output_path, format=format)
        print(f"Image saved to: {output_path}")
        return str(output_path)
    
    def save_sequence(self, output_dir: Optional[str] = None,
                     format: str = 'PNG', normalize: bool = True,
                     start_frame: int = 0, end_frame: Optional[int] = None,
                     frame_step: int = 1) -> list:
        """
        Save all frames from a sequence to individual files.
        
        Args:
            output_dir: Output directory (default: same as input file directory)
            format: Image format (PNG, JPEG, etc.)
            normalize: Whether to normalize pixel values to 0-255 range
            start_frame: First frame to save (default: 0)
            end_frame: Last frame to save (default: last frame)
            frame_step: Step between frames (default: 1, saves all frames)
        
        Returns:
            List of paths to saved images
        """
        if self.pixel_array is None:
            self.extract_image()
        
        if not self.is_sequence():
            raise ValueError("Not a sequence. Use save_image() instead.")
        
        num_frames = self.get_num_frames()
        if end_frame is None:
            end_frame = num_frames - 1
        
        # Validate frame range
        start_frame = max(0, min(start_frame, num_frames - 1))
        end_frame = max(start_frame, min(end_frame, num_frames - 1))
        
        # Determine output directory
        if output_dir is None:
            output_dir = self.dicom_path.parent / f"{self.dicom_path.stem}_frames"
        else:
            output_dir = Path(output_dir)
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        saved_paths = []
        frames_to_save = list(range(start_frame, end_frame + 1, frame_step))
        total_frames = len(frames_to_save)
        
        print(f"Saving {total_frames} frames to {output_dir}...")
        
        for i, frame_idx in enumerate(frames_to_save):
            # Get frame
            frame_data = self.get_frame(frame_idx)
            
            # Normalize and convert
            frame_data = self._normalize_image(frame_data, normalize)
            img = self._array_to_image(frame_data)
            
            # Save frame
            frame_path = output_dir / f"frame_{frame_idx:04d}.{format.lower()}"
            img.save(frame_path, format=format)
            saved_paths.append(str(frame_path))
            
            # Progress indicator
            if (i + 1) % 50 == 0 or (i + 1) == total_frames:
                print(f"  Progress: {i + 1}/{total_frames} frames saved")
        
        print(f"All frames saved to: {output_dir}")
        return saved_paths
    
    def save_metadata(self, output_path: Optional[str] = None, 
                     format: str = 'json', include_private: bool = False) -> str:
        """
        Save metadata to a file.
        
        Args:
            output_path: Output file path
            format: Output format ('json' or 'txt')
            include_private: Whether to include private tags
        
        Returns:
            Path to saved metadata file
        """
        metadata = self.get_metadata(include_private=include_private)
        
        # Determine output path
        if output_path is None:
            ext = '.json' if format == 'json' else '.txt'
            output_path = self.dicom_path.with_suffix(ext)
        else:
            output_path = Path(output_path)
        
        if format == 'json':
            with open(output_path, 'w') as f:
                json.dump(metadata, f, indent=2, default=str)
        else:
            with open(output_path, 'w') as f:
                f.write("DICOM Metadata\n")
                f.write("=" * 50 + "\n\n")
                for tag, info in sorted(metadata.items()):
                    f.write(f"Tag: {tag}\n")
                    f.write(f"  Keyword: {info.get('keyword', 'N/A')}\n")
                    f.write(f"  VR: {info.get('VR', 'N/A')}\n")
                    f.write(f"  Value: {info.get('value', 'N/A')}\n")
                    f.write("\n")
        
        print(f"Metadata saved to: {output_path}")
        return str(output_path)


def main():
    """Main function for command-line usage."""
    parser = argparse.ArgumentParser(
        description='Extract images and metadata from DICOM files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract image and metadata from a DICOM file
  python dicom_extractor.py input.dcm
  
  # Save image to specific path
  python dicom_extractor.py input.dcm --image output.png
  
  # Save all frames from a sequence
  python dicom_extractor.py input.dcm --save-sequence
  
  # Save specific frame from a sequence
  python dicom_extractor.py input.dcm --frame 100
  
  # Save every 10th frame from a sequence
  python dicom_extractor.py input.dcm --save-sequence --frame-step 10
  
  # Save frames 50-100 from a sequence
  python dicom_extractor.py input.dcm --save-sequence --start-frame 50 --end-frame 100
  
  # Save metadata to JSON
  python dicom_extractor.py input.dcm --metadata output.json
  
  # Include private tags in metadata
  python dicom_extractor.py input.dcm --include-private
        """
    )
    
    parser.add_argument('dicom_file', type=str, help='Path to DICOM file')
    parser.add_argument('--image', '-i', type=str, help='Output path for extracted image')
    parser.add_argument('--metadata', '-m', type=str, help='Output path for metadata')
    parser.add_argument('--format', '-f', choices=['json', 'txt'], default='json',
                       help='Metadata output format (default: json)')
    parser.add_argument('--include-private', action='store_true',
                       help='Include private tags in metadata')
    parser.add_argument('--no-normalize', action='store_true',
                       help='Do not normalize pixel values when saving image')
    parser.add_argument('--image-format', choices=['PNG', 'JPEG', 'TIFF'], default='PNG',
                       help='Image output format (default: PNG)')
    parser.add_argument('--common-only', action='store_true',
                       help='Display only common metadata fields')
    parser.add_argument('--save-sequence', action='store_true',
                       help='Save all frames from a sequence to individual files')
    parser.add_argument('--output-dir', type=str,
                       help='Output directory for sequence frames (default: <filename>_frames)')
    parser.add_argument('--frame', type=int,
                       help='For sequences, save only this specific frame index')
    parser.add_argument('--start-frame', type=int, default=0,
                       help='First frame to save when saving sequence (default: 0)')
    parser.add_argument('--end-frame', type=int,
                       help='Last frame to save when saving sequence (default: last frame)')
    parser.add_argument('--frame-step', type=int, default=1,
                       help='Step between frames when saving sequence (default: 1, saves all)')
    
    args = parser.parse_args()
    
    try:
        # Create extractor
        extractor = DICOMExtractor(args.dicom_file)
        extractor.load()
        
        # Extract and display common metadata
        print("\n" + "=" * 50)
        print("Common Metadata:")
        print("=" * 50)
        common_meta = extractor.get_common_metadata()
        for key, value in common_meta.items():
            print(f"{key}: {value}")
        
        # Extract image
        print("\n" + "=" * 50)
        print("Extracting image...")
        print("=" * 50)
        extractor.extract_image()
        
        # Handle sequence vs single image
        if extractor.is_sequence():
            if args.save_sequence:
                # Save all frames from sequence
                extractor.save_sequence(
                    output_dir=args.output_dir,
                    format=args.image_format,
                    normalize=not args.no_normalize,
                    start_frame=args.start_frame,
                    end_frame=args.end_frame,
                    frame_step=args.frame_step
                )
            elif args.frame is not None:
                # Save specific frame
                extractor.save_image(
                    output_path=args.image,
                    format=args.image_format,
                    normalize=not args.no_normalize,
                    frame_index=args.frame
                )
            else:
                # Save first frame by default
                print("Note: This is a sequence. Saving first frame only.")
                print("      Use --save-sequence to save all frames, or --frame N for a specific frame.")
                extractor.save_image(
                    output_path=args.image,
                    format=args.image_format,
                    normalize=not args.no_normalize,
                    frame_index=0
                )
        else:
            # Single image
            if args.image:
                extractor.save_image(
                    output_path=args.image,
                    format=args.image_format,
                    normalize=not args.no_normalize
                )
            else:
                # Auto-save image
                extractor.save_image(normalize=not args.no_normalize)
        
        # Save metadata if requested
        if args.metadata:
            extractor.save_metadata(
                output_path=args.metadata,
                format=args.format,
                include_private=args.include_private
            )
        elif not args.common_only:
            # Auto-save metadata
            extractor.save_metadata(
                format=args.format,
                include_private=args.include_private
            )
        
        print("\n" + "=" * 50)
        print("Extraction complete!")
        print("=" * 50)
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()

