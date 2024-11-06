#!/bin/bash

set -eo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuration
UBUNTU_VERSION="24.10"
UBUNTU_IMAGE_URL="https://cdimage.ubuntu.com/releases/24.10/release/ubuntu-24.10-preinstalled-desktop-arm64+raspi.img.xz"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKDIR="${SCRIPT_DIR}/build"
OUTPUT_IMAGE="ubuntu-pi-custom.img"
DOWNLOAD_FILENAME="ubuntu-24.10-preinstalled-desktop-arm64+raspi.img.xz"
IMAGE_FILENAME="ubuntu-24.10-preinstalled-desktop-arm64+raspi.img"  # Added this line

# Log functions
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%dT%H:%M:%S%z')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%dT%H:%M:%S%z')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%dT%H:%M:%S%z')] ERROR: $1${NC}"
    exit 1
}

# Check if running with sudo
check_sudo() {
    if [ "$EUID" -ne 0 ]; then
        error "Please run this script with sudo"
    fi
}

# Check for required tools
check_requirements() {
    local required_tools=(
        "wget"
        "xz"
        "fdisk"
        "mount"
        "mkpasswd"
        "sha256sum"
    )

    log "Checking for required tools..."
    for tool in "${required_tools[@]}"; do
        if ! command -v "$tool" &> /dev/null; then
            error "Required tool '$tool' is not installed. Please install it first."
        fi
    done
}

# Create working directory
setup_workdir() {
    log "Setting up working directory..."
    mkdir -p "$WORKDIR"
    cd "$WORKDIR"
}

# Verify downloaded file
verify_download() {
    local file="$1"
    local expected_size
    local actual_size
    
    # Get expected file size from server
    expected_size=$(wget --spider --server-response "$UBUNTU_IMAGE_URL" 2>&1 | grep "Content-Length" | awk '{print $2}')
    actual_size=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file")
    
    if [ "$actual_size" != "$expected_size" ]; then
        warn "Downloaded file size ($actual_size) doesn't match expected size ($expected_size)"
        return 1
    fi
    
    return 0
}

# Download Ubuntu image
download_image() {
    local download_path="${WORKDIR}/${DOWNLOAD_FILENAME}"
    
    # Check if file already exists in working directory
    if [ -f "$download_path" ]; then
        log "Found existing download, verifying..."
        if verify_download "$download_path"; then
            log "Existing download verified, skipping download"
            return 0
        else
            warn "Existing download appears incomplete or corrupted, re-downloading..."
            rm "$download_path"
        fi
    fi

    log "Downloading Ubuntu $UBUNTU_VERSION image..."
    wget -c "$UBUNTU_IMAGE_URL" -O "$download_path" || error "Download failed"
    
    # Verify download
    verify_download "$download_path" || error "Download verification failed"
}

# Extract image
extract_image() {
    local xz_file="${WORKDIR}/${DOWNLOAD_FILENAME}"
    local img_file="${WORKDIR}/${IMAGE_FILENAME}"
    
    if [ -f "$img_file" ]; then
        log "Found existing extracted image, skipping extraction"
        return 0
    fi
    
    log "Extracting image..."
    xz -d -k "$xz_file" || error "Extraction failed"
}

# Mount image and modify it
modify_image() {
    local img_file="${WORKDIR}/${IMAGE_FILENAME}"
    
    if [ ! -f "$img_file" ]; then
        error "Image file not found: $img_file"
    fi
    
    log "Mounting image..."
    
    # Get start sector of second partition
    OFFSET=$(fdisk -l "$img_file" | grep "2 *" | awk '{print $2}')
    if [ -z "$OFFSET" ]; then
        error "Failed to find second partition offset"
    fi
    
    SECTOR_SIZE=$(fdisk -l "$img_file" | grep "Sector size" | awk '{print $4}')
    if [ -z "$SECTOR_SIZE" ]; then
        error "Failed to find sector size"
    fi
    
    MOUNT_OFFSET=$((OFFSET * SECTOR_SIZE))

    # Create mount point
    mkdir -p "${WORKDIR}/mnt"
    
    # Mount image
    mount -o offset="$MOUNT_OFFSET" "$img_file" "${WORKDIR}/mnt" || error "Failed to mount image"

    log "Modifying image..."
    
    # Check if required files exist
    if [ ! -f "${SCRIPT_DIR}/user_data.yaml" ]; then
        error "user_data.yaml not found in script directory"
    fi
    
    if [ ! -f "${SCRIPT_DIR}/network-config" ]; then
        error "network-config not found in script directory"
    fi
    
    # Copy cloud-init configuration
    mkdir -p "${WORKDIR}/mnt/var/lib/cloud/scripts/per-instance"
    cp "${SCRIPT_DIR}/user_data.yaml" "${WORKDIR}/mnt/var/lib/cloud/scripts/per-instance/"
    
    # Copy network configuration
    mkdir -p "${WORKDIR}/mnt/etc/netplan"
    cp "${SCRIPT_DIR}/network-config" "${WORKDIR}/mnt/etc/netplan/50-cloud-init.yaml"

    # Unmount
    umount "${WORKDIR}/mnt" || error "Failed to unmount image"
}

# Create final image
create_final_image() {
    local img_file="${WORKDIR}/${IMAGE_FILENAME}"
    
    log "Creating final image..."
    cp "$img_file" "${SCRIPT_DIR}/${OUTPUT_IMAGE}" || error "Failed to copy final image"
    
    log "Cleaning up..."
    cd "$SCRIPT_DIR"
    rm -rf "$WORKDIR"
    
    log "Custom image created: $OUTPUT_IMAGE"
    log "You can now write this image to an SD card using:"
    log "sudo dd if=$OUTPUT_IMAGE of=/dev/sdX bs=4M status=progress conv=fsync"
    log "Replace /dev/sdX with your SD card device!"
}

# Cleanup function
cleanup() {
    if mountpoint -q "${WORKDIR}/mnt" 2>/dev/null; then
        log "Cleaning up mounted filesystem..."
        umount "${WORKDIR}/mnt"
    fi
}

# Main function
main() {
    check_sudo
    check_requirements
    setup_workdir
    download_image
    extract_image
    modify_image
    create_final_image
}

# Set up cleanup trap
trap cleanup EXIT

# Run main function
main