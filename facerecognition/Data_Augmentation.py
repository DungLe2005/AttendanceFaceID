import os
import cv2
import numpy as np
from tqdm import tqdm

class ImageAugmenter:
    def __init__(self, input_folder, output_folder):
        self.input_folder = input_folder
        self.output_folder = output_folder

    def rotate(self, image, angle):
        rows, cols = image.shape[:2]
        M = cv2.getRotationMatrix2D((cols/2, rows/2), angle, 1)
        img_rotated = cv2.warpAffine(image, M, (cols, rows))
        return img_rotated

    def flip(self, image):
        img_flipped = cv2.flip(image, 0)
        return img_flipped

    def add_noise(self, image, percent):
        noise = np.random.normal(0, 1, image.shape)
        img_noisy = image + percent * noise * 255
        img_noisy = np.clip(img_noisy, 0, 255).astype(np.uint8)
        return img_noisy

    def augment(self, angle=15, percent=0.05):
        total_files = 0
        processed_files = 0

        for root, _, files in os.walk(self.input_folder):
            for filename in tqdm(files):
                total_files += 1
                input_path = os.path.join(root, filename)
                img = cv2.imread(input_path)

                if img is None:
                    print(f"Warning: không đọc được ảnh {input_path}, bỏ qua.")
                    continue  # bỏ qua file hỏng

                # rotate left image
                img_rotated_left = self.rotate(img, angle)

                # rotate right image
                img_rotated_right = self.rotate(img, -angle)

                # add noise to image
                img_noisy = self.add_noise(img, percent)

                # create output directory
                relative_path = os.path.relpath(root, self.input_folder)
                output_path = os.path.join(self.output_folder, relative_path)
                os.makedirs(output_path, exist_ok=True)

                # save augmented images
                cv2.imwrite(os.path.join(output_path, f"rotated_left_{filename}"), img_rotated_left)
                cv2.imwrite(os.path.join(output_path, f"rotated_right_{filename}"), img_rotated_right)
                cv2.imwrite(os.path.join(output_path, f"noise_{filename}"), img_noisy)

                processed_files += 1

        print(f"Tổng số file: {total_files}, Số file xử lý thành công: {processed_files}")


if __name__ == '__main__':
    currentPythonFilePath = os.getcwd()
    input_dir = os.path.join(currentPythonFilePath, "static/data/")
    output_dir = os.path.join(currentPythonFilePath, "static/data_process/raw/")

    augmenter = ImageAugmenter(input_dir, output_dir)
    augmenter.augment()
