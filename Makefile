.PHONY: prototype-workspace

prototype-workspace:
	python3 -m http.server 4173 --directory prototypes/workspace
