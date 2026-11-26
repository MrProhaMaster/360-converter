import sys

if __name__ == "__main__":
    if sys.argv[1:2] == ["--cli"]:
        from converter_360.cli import main
        raise SystemExit(main(sys.argv[2:]))
    else:
        from converter_360.gui import main
        main()
