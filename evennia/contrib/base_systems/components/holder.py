"""
Components - ChrisLR 2022

This file contains the classes that allow a typeclass to use components.
"""

from evennia.contrib.base_systems import components


class ComponentProperty:
    """
    This allows you to register a component on a typeclass.
    Components registered with this property are automatically added
    to any instance of this typeclass.

    Defaults can be overridden for this typeclass by passing kwargs
    """
    def __init__(self, component_name, **kwargs):
        """
        Initializes the descriptor

        Args:
            component_name (str): The name of the component
            **kwargs (any): Key=Values overriding default values of the component
        """
        self.component_name = component_name
        self.values = kwargs

    def __get__(self, instance, owner):
        component = instance.components.get(self.component_name)
        return component

    def __set__(self, instance, value):
        raise Exception("Cannot set a class property")

    def __set_name__(self, owner, name):
        class_components = getattr(owner, "_class_components", None)
        if not class_components:
            class_components = []
            setattr(owner, "_class_components", class_components)

        class_components.append((self.component_name, self.values))


class ComponentHandler:
    """
    This is the handler that will be added to any typeclass that inherits from ComponentHolder.
    It lets you add or remove components and will load components as needed.
    It stores the list of registered components on the host .db with component_names as key.
    """
    def __init__(self, host):
        self.host = host
        self._loaded_components = {}

    def add(self, component):
        """
        Method to add a Component to a host.
        It caches the loaded component and appends its name to the host's component name list.
        It will also call the component's 'at_added' method, passing its host.

        Args:
            component (object): The 'loaded' component instance to add.

        """
        self._set_component(component)
        self.db_names.append(component.name)
        self.host.tags.add(component.name, category="components")
        component.at_added(self.host)
        for tag_field_name in component.tag_field_names:
            default_tag = type(component).__dict__[tag_field_name]._default
            if default_tag:
                setattr(component, tag_field_name, default_tag)

    def add_default(self, name):
        """
        Method to add a Component initialized to default values on a host.
        It will retrieve the proper component and instanciate it with 'default_create'.
        It will cache this new component and add it to its list.
        It will also call the component's 'at_added' method, passing its host.

        Args:
            name (str): The name of the component class to add.

        """
        component = components.get_component_class(name)
        if not component:
            raise ComponentDoesNotExist(f"Component {name} does not exist.")

        new_component = component.default_create(self.host)
        self._set_component(new_component)
        self.db_names.append(name)
        self.host.tags.add(name, category="components")
        new_component.at_added(self.host)
        for tag_field_name in component.tag_field_names:
            default_tag = type(component).__dict__[tag_field_name]._default
            if default_tag:
                setattr(component, tag_field_name, default_tag)

    def remove(self, component):
        """
        Method to remove a component instance from a host.
        It removes the component from the cache and listing.
        It will call the component's 'at_removed' method.

        Args:
            component (object): The component instance to remove.

        """
        component_name = component.name
        if component_name in self._loaded_components:
            component.at_removed(self.host)
            self.db_names.remove(component_name)
            self.host.tags.remove(component_name, category="components")
            for tag_field_name in component.tag_field_names:
                self.host.tags.remove()
            del self._loaded_components[component_name]
        else:
            message = f"Cannot remove {component_name} from {self.host.name} as it is not registered."
            raise ComponentIsNotRegistered(message)

    def remove_by_name(self, name):
        """
        Method to remove a component instance from a host.
        It removes the component from the cache and listing.
        It will call the component's 'at_removed' method.

        Args:
            name (str): The name of the component to remove.

        """
        instance = self.get(name)
        if not instance:
            message = f"Cannot remove {name} from {self.host.name} as it is not registered."
            raise ComponentIsNotRegistered(message)

        instance.at_removed(self.host)
        self.db_names.remove(name)
        self.host.tags.remove(name, category="components")
        del self._loaded_components[name]

    def get(self, name):
        """
        Method to retrieve a cached Component instance by its name.

        Args:
            name (str): The name of the component to retrieve.

        """
        return self._loaded_components.get(name)

    def has(self, name):
        """
        Method to check if a component is registered and ready.

        Args:
            name (str): The name of the component.

        """
        return name in self._loaded_components

    def initialize(self):
        """
        Method that loads and caches each component currently registered on the host.
        It retrieves the names from the registered listing and calls 'load' on each
        prototype class that can be found from this listing.

        """
        component_names = self.db_names
        if not component_names:
            return

        for component_name in component_names:
            component = components.get_component_class(component_name)
            if component:
                component_instance = component.load(self.host)
                self._set_component(component_instance)
            else:
                message = f"Could not initialize runtime component {component_name} of {self.host.name}"
                raise ComponentDoesNotExist(message)

    def _set_component(self, component):
        self._loaded_components[component.name] = component

    @property
    def db_names(self):
        """
        Property shortcut to retrieve the registered component names

        Returns:
            component_names (iterable): The name of each component that is registered

        """
        return self.host.attributes.get("component_names")

    def __getattr__(self, name):
        return self.get(name)


class ComponentHolderMixin(object):
    """
    Mixin to add component support to a typeclass

    Components are set on objects using the component.name as an object attribute.
    All registered components are initialized on the typeclass.
    They will be of None value if not present in the class components or runtime components.
    """

    def at_init(self):
        """
        Method that initializes the ComponentHandler.
        """
        super(ComponentHolderMixin, self).at_init()
        setattr(self, "_component_handler", ComponentHandler(self))
        self.components.initialize()

    def basetype_setup(self):
        """
        Method that initializes the ComponentHandler, creates and registers all
        components that were set on the typeclass using ComponentProperty.
        """
        super().basetype_setup()
        component_names = []
        setattr(self, "_component_handler", ComponentHandler(self))
        class_components = getattr(self, "_class_components", ())
        for component_name, values in class_components:
            component_class = components.get_component_class(component_name)
            component = component_class.create(self, **values)
            component_names.append(component_name)
            self.components._loaded_components[component_name] = component
            for tag_field_name in component.tag_field_names:
                default_tag = type(component).__dict__[tag_field_name]._default
                if default_tag:
                    setattr(component, tag_field_name, default_tag)

        self.db.component_names = component_names

    def basetype_posthook_setup(self):
        """
        Method that add component related tags that were set using ComponentProperty.
        """
        super().basetype_posthook_setup()
        for component_name in self.db.component_names:
            self.tags.add(component_name, category="components")

    @property
    def components(self) -> ComponentHandler:
        """
        Property getter to retrieve the component_handler.
        Returns:
            ComponentHandler: This Host's ComponentHandler
        """
        return getattr(self, "_component_handler", None)

    @property
    def cmp(self) -> ComponentHandler:
        """
        Shortcut Property getter to retrieve the component_handler.
        Returns:
            ComponentHandler: This Host's ComponentHandler
        """
        return self.components


class ComponentDoesNotExist(Exception):
    pass


class ComponentIsNotRegistered(Exception):
    pass
