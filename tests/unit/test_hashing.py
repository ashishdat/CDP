"""SHA-256 exact-duplicate hashing and perceptual near-duplicate hashing."""

from PIL import Image

from packages.storage.hashing import hamming_distance, perceptual_hash, sha256_bytes


def test_sha256_is_deterministic():
    data = b"claim document bytes"
    assert sha256_bytes(data) == sha256_bytes(data)


def test_sha256_differs_for_different_bytes():
    assert sha256_bytes(b"a") != sha256_bytes(b"b")


def test_sha256_matches_known_vector():
    # sha256("") — a stable, well-known test vector
    assert sha256_bytes(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_perceptual_hash_identical_for_identical_images():
    img = Image.new("L", (64, 64), color=128)
    assert perceptual_hash(img) == perceptual_hash(img.copy())


def test_perceptual_hash_close_for_lightly_perturbed_image():
    img = Image.new("L", (64, 64), color=255)
    img.paste(0, (5, 5, 20, 20))
    perturbed = img.copy()
    perturbed.paste(10, (5, 5, 20, 20))  # near-black -> slightly-less-black
    distance = hamming_distance(perceptual_hash(img), perceptual_hash(perturbed))
    assert distance <= 4  # small perturbation should barely move the hash


def test_perceptual_hash_far_for_very_different_images():
    # Uniform images are a degenerate case for average-hash (every pixel
    # equals the average, so all bits collapse to the same value regardless
    # of the constant) -- use a checkerboard vs. its inverse instead, which
    # is the standard way to exercise real bit disagreement.
    checkerboard = Image.new("L", (64, 64))
    inverse = Image.new("L", (64, 64))
    for y in range(64):
        for x in range(64):
            is_light = (x // 8 + y // 8) % 2 == 0
            checkerboard.putpixel((x, y), 255 if is_light else 0)
            inverse.putpixel((x, y), 0 if is_light else 255)
    distance = hamming_distance(perceptual_hash(checkerboard), perceptual_hash(inverse))
    assert distance >= 32  # roughly maximal disagreement (64-bit hash)
