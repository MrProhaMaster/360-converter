import sys

if __name__ == "__main__":
    if sys.argv[1:2] == ["--cli"]:
        from pano360.cli import main
        raise SystemExit(main(sys.argv[2:]))
    else:
        from pano360.gui import main
        main()
