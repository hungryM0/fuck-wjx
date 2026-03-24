import sys
import os

if len(sys.argv) > 1 and sys.argv[1] == "--cli":
    from wjx.cli.main import main as cli_main
    sys.argv.pop(1)
    sys.exit(cli_main())
else:
    from wjx.main import main
    main()
    
