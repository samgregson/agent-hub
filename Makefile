.PHONY: prototype-workspace

prototype-workspace:
	python3 -m http.server 4174 --bind 127.0.0.1 --directory prototypes/workspace
