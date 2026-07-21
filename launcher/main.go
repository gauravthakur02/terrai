// terraai-launcher is the single .exe users download and run. It exists so
// TerraAI can ship as one file without paying PyInstaller onefile's
// extraction-on-every-launch cost (measured at ~7-8s vs ~1-1.5s for the
// same app run as a onedir build — see repo history for the measurements).
//
// A payload zip (the PyInstaller onedir build of the real app) and a fixed
// 72-byte footer are appended to this binary at package time by
// scripts/package_windows.py — see readFooter for the exact layout. On
// first run (or after an upgrade) it extracts that payload to a stable
// per-user cache directory; on every run after that it skips straight to
// relaunching the already-extracted terraai.exe, which starts as fast as
// plain onedir because no extraction happens at all.
package main

import (
	"archive/zip"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// versionFieldSize + lengthFieldSize, appended after the payload zip by the
// packaging script. Keep in sync with scripts/package_windows.py.
const (
	versionFieldSize = 64
	lengthFieldSize  = 8
	footerSize       = versionFieldSize + lengthFieldSize
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "terraai launcher error:", err)
		os.Exit(1)
	}
}

func run() error {
	selfPath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("locating self: %w", err)
	}
	selfPath, err = filepath.EvalSymlinks(selfPath)
	if err != nil {
		return fmt.Errorf("resolving self path: %w", err)
	}

	version, payloadOffset, payloadLen, err := readFooter(selfPath)
	if err != nil {
		return fmt.Errorf("reading embedded payload (was this exe packaged correctly?): %w", err)
	}

	installDir, err := installDir()
	if err != nil {
		return err
	}
	targetExe := filepath.Join(installDir, "terraai.exe")
	markerPath := filepath.Join(installDir, ".version")

	if !isUpToDate(markerPath, version) {
		if err := extractPayload(selfPath, payloadOffset, payloadLen, installDir); err != nil {
			return fmt.Errorf("extracting: %w", err)
		}
		// Written only after a fully successful extraction — an interrupted
		// extract (crash, disk full) leaves no marker, so the next launch
		// just retries instead of treating a half-written install as good.
		if err := os.WriteFile(markerPath, []byte(version), 0o644); err != nil {
			return fmt.Errorf("writing version marker: %w", err)
		}
	}

	return relaunch(targetExe, os.Args[1:])
}

// readFooter reads the [64-byte version][8-byte big-endian payload length]
// footer written by scripts/package_windows.py at the very end of this exe,
// and derives where the embedded zip payload starts.
func readFooter(selfPath string) (version string, payloadOffset int64, payloadLen int64, err error) {
	f, err := os.Open(selfPath)
	if err != nil {
		return "", 0, 0, err
	}
	defer f.Close()

	info, err := f.Stat()
	if err != nil {
		return "", 0, 0, err
	}
	size := info.Size()
	if size < footerSize {
		return "", 0, 0, fmt.Errorf("file too small to contain footer (%d bytes)", size)
	}

	footer := make([]byte, footerSize)
	if _, err := f.ReadAt(footer, size-footerSize); err != nil {
		return "", 0, 0, err
	}

	version = strings.TrimRight(string(footer[:versionFieldSize]), "\x00")
	var length uint64
	for _, b := range footer[versionFieldSize:] {
		length = length<<8 | uint64(b)
	}
	payloadLen = int64(length)
	payloadOffset = size - footerSize - payloadLen
	if payloadOffset < 0 || payloadLen <= 0 {
		return "", 0, 0, fmt.Errorf("corrupt footer: offset=%d len=%d", payloadOffset, payloadLen)
	}
	return version, payloadOffset, payloadLen, nil
}

func installDir() (string, error) {
	cacheDir, err := os.UserCacheDir()
	if err != nil {
		return "", fmt.Errorf("resolving cache dir: %w", err)
	}
	parent := filepath.Join(cacheDir, "TerraAI")
	if err := os.MkdirAll(parent, 0o755); err != nil {
		return "", err
	}
	return filepath.Join(parent, "app"), nil
}

func isUpToDate(markerPath, version string) bool {
	data, err := os.ReadFile(markerPath)
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(data)) == version
}

// extractPayload unzips into a temp sibling directory and only swaps it
// into destDir on full success, so a failed/interrupted extraction never
// leaves a partial install in place.
func extractPayload(selfPath string, payloadOffset, payloadLen int64, destDir string) error {
	self, err := os.Open(selfPath)
	if err != nil {
		return err
	}
	defer self.Close()

	sr := io.NewSectionReader(self, payloadOffset, payloadLen)
	zr, err := zip.NewReader(sr, payloadLen)
	if err != nil {
		return fmt.Errorf("reading embedded zip: %w", err)
	}

	tmpDir := destDir + ".tmp"
	if err := os.RemoveAll(tmpDir); err != nil {
		return err
	}
	if err := os.MkdirAll(tmpDir, 0o755); err != nil {
		return err
	}

	cleanTmp := filepath.Clean(tmpDir) + string(os.PathSeparator)
	for _, f := range zr.File {
		target := filepath.Join(tmpDir, f.Name)
		if !strings.HasPrefix(target, cleanTmp) {
			return fmt.Errorf("unsafe path in payload: %s", f.Name)
		}
		if f.FileInfo().IsDir() {
			if err := os.MkdirAll(target, 0o755); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		if err := extractOne(f, target); err != nil {
			return err
		}
	}

	if err := os.RemoveAll(destDir); err != nil {
		return err
	}
	return os.Rename(tmpDir, destDir)
}

func extractOne(f *zip.File, target string) error {
	rc, err := f.Open()
	if err != nil {
		return err
	}
	defer rc.Close()

	out, err := os.OpenFile(target, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, f.Mode())
	if err != nil {
		return err
	}
	defer out.Close()

	_, err = io.Copy(out, rc)
	return err
}

// relaunch execs the real app, forwarding argv and stdio, and mirrors its
// exit code — transparent to callers/scripts wrapping this launcher.
func relaunch(targetExe string, args []string) error {
	cmd := exec.Command(targetExe, args...)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	err := cmd.Run()
	if err == nil {
		os.Exit(0)
	}
	if exitErr, ok := err.(*exec.ExitError); ok {
		os.Exit(exitErr.ExitCode())
	}
	return err
}
